"""
Agent graph execution and event streaming.
"""
import uuid
import os
from typing import Dict, Any, Iterator, List
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage, SystemMessage
from app.agents.graphs.graph import create_agent_graph
from app.agents.graphs.state import AgentState
from app.agents.checkpoint import get_checkpoint_config, get_checkpoint_saver
from app.agents.config import MAX_ITERATIONS, LANGCHAIN_TRACING_V2, LANGCHAIN_PROJECT, LANGFUSE_ENABLED
from app.agents.agents.supervisor import SupervisorAgent
from app.agents.agents.greeter import GreeterAgent
from app.core.logging import get_logger
from app.observability.tracing import get_callback_handler, prepare_trace_context, flush_traces

logger = get_logger(__name__)

# Enable LangSmith tracing if configured (optional, for compatibility)
if LANGCHAIN_TRACING_V2:
    os.environ['LANGCHAIN_TRACING_V2'] = 'true'
    os.environ['LANGCHAIN_PROJECT'] = LANGCHAIN_PROJECT

supervisor_agent = SupervisorAgent()
greeter_agent = GreeterAgent()


def load_conversation_history(chat_session_id: int) -> List[BaseMessage]:
    """
    Load conversation history from database and convert to LangChain messages.
    
    Args:
        chat_session_id: Chat session ID
        
    Returns:
        List of LangChain BaseMessage objects in chronological order
    """
    from app.services.chat_service import get_messages
    from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
    
    # Get all messages from database
    db_messages = get_messages(chat_session_id)
    
    # Convert to LangChain message format
    langchain_messages = []
    for msg in db_messages:
        if msg.role == 'user':
            langchain_messages.append(HumanMessage(content=msg.content))
        elif msg.role == 'assistant':
            # Create AIMessage with metadata if available
            metadata = msg.metadata or {}
            aimessage = AIMessage(content=msg.content)
            if metadata:
                aimessage.response_metadata = metadata
            langchain_messages.append(aimessage)
        elif msg.role == 'system':
            langchain_messages.append(SystemMessage(content=msg.content))
    
    return langchain_messages


def execute_agent(
    user_id: int,
    chat_session_id: int,
    message: str
) -> Dict[str, Any]:
    """
    Execute agent graph with input message.
    
    Args:
        user_id: User ID
        chat_session_id: Chat session ID
        message: User message
        
    Returns:
        Dictionary with execution results
    """
    from app.agents.checkpoint import get_checkpoint_saver
    from langfuse import get_client, propagate_attributes
    
    # Generate deterministic trace ID using Langfuse SDK
    langfuse = get_client() if LANGFUSE_ENABLED else None
    if langfuse:
        # Use chat_session_id and message as seed for deterministic trace ID
        trace_seed = f"{chat_session_id}-{user_id}-{uuid.uuid4()}"
        trace_id = langfuse.create_trace_id(seed=trace_seed)
    else:
        trace_id = str(uuid.uuid4())
    
    # Get checkpoint config
    config = get_checkpoint_config(chat_session_id)
    
    # Add Langfuse callback to config if enabled
    if LANGFUSE_ENABLED:
        callback_handler = get_callback_handler()
        if callback_handler:
            # Add callback to config - LangGraph expects callbacks at top level
            if isinstance(config, dict):
                if 'callbacks' not in config:
                    config['callbacks'] = []
                # Add callback if not already present
                if callback_handler not in config['callbacks']:
                    config['callbacks'].append(callback_handler)
                # Also ensure configurable exists for thread_id
                if 'configurable' not in config:
                    config['configurable'] = {}
            else:
                if not hasattr(config, 'callbacks') or config.callbacks is None:
                    config.callbacks = []
                if callback_handler not in config.callbacks:
                    config.callbacks.append(callback_handler)
                if not hasattr(config, 'configurable') or config.configurable is None:
                    config.configurable = {}
    
    # Load conversation history from database (includes the user message that was just saved)
    conversation_history = load_conversation_history(chat_session_id)
    
    # Check if the last message is the current user message (to avoid duplication)
    last_message = conversation_history[-1] if conversation_history else None
    if last_message and isinstance(last_message, HumanMessage) and last_message.content == message:
        # User message already in history, use it as-is
        all_messages = conversation_history
        logger.debug(f"Loaded {len(conversation_history)} messages (including current user message)")
    else:
        # User message not in history yet (shouldn't happen, but handle it)
        new_user_message = HumanMessage(content=message)
        all_messages = conversation_history + [new_user_message]
        logger.debug(f"Loaded {len(conversation_history)} previous messages, adding new user message (total: {len(all_messages)} messages)")
    
    # Prepare initial state
    initial_state: AgentState = {
        "messages": all_messages,
        "current_agent": None,
        "chat_session_id": chat_session_id,
        "user_id": user_id,
        "tool_calls": [],
        "metadata": {
            "trace_id": trace_id,
        },
        "next_agent": None,
    }
    
    # Execute graph with checkpoint context
    try:
        logger.info(f"Executing agent for user {user_id}, session {chat_session_id}, trace: {trace_id}")
        
        # Use checkpoint saver as context manager
        with get_checkpoint_saver() as checkpoint_saver:
            # Create graph with checkpoint
            graph = create_agent_graph(checkpoint_saver=checkpoint_saver)
            
            # Use propagate_attributes at graph invocation level
            # This sets user_id, session_id, and metadata on all traces
            if LANGFUSE_ENABLED:
                trace_context = prepare_trace_context(
                    user_id=user_id,
                    session_id=chat_session_id,
                    metadata={
                        "chat_session_id": chat_session_id,
                        "execution_type": "graph",
                        "trace_id": trace_id,
                    }
                )
                
                with propagate_attributes(**trace_context):
                    final_state = graph.invoke(initial_state, config=config)
            else:
                final_state = graph.invoke(initial_state, config=config)
            
            # Extract final response
            messages = final_state.get("messages", [])
            last_message = messages[-1] if messages else None
            
            response_text = ""
            if isinstance(last_message, AIMessage):
                response_text = last_message.content
            
            # Flush traces if Langfuse is enabled
            if LANGFUSE_ENABLED:
                flush_traces()
            
            logger.info(f"Agent execution completed successfully. Agent: {final_state.get('current_agent')}")
            
            return {
                "success": True,
                "response": response_text,
                "agent": final_state.get("current_agent"),
                "tool_calls": final_state.get("tool_calls", []),
                "trace_id": trace_id,
            }
    except Exception as e:
        logger.error(
            f"Error executing agent for user {user_id}, session {chat_session_id}: {e}",
            exc_info=True
        )
        
        # Flush traces even on error
        if LANGFUSE_ENABLED:
            flush_traces()
        
        return {
            "success": False,
            "error": str(e),
            "response": f"I apologize, but I encountered an error: {str(e)}",
            "trace_id": trace_id,
        }


def stream_agent_events(
    user_id: int,
    chat_session_id: int,
    message: str
) -> Iterator[Dict[str, Any]]:
    """
    Stream agent execution events token-by-token using LangGraph's native streaming.
    
    Uses graph.stream() with stream_mode=["messages", "updates"] to stream tokens while
    maintaining the full graph structure and automatic trace creation. The graph execution
    automatically creates the proper chain structure (supervisor → greeter → LLM) through
    Langfuse callbacks, matching the non-streaming trace structure.
    
    Args:
        user_id: User ID
        chat_session_id: Chat session ID
        message: User message
        
    Yields:
        Event dictionaries with type and data
    """
    from langfuse import get_client, propagate_attributes
    from app.agents.checkpoint import get_checkpoint_saver
    
    # Generate deterministic trace ID using Langfuse SDK
    langfuse = get_client() if LANGFUSE_ENABLED else None
    if langfuse:
        trace_seed = f"{chat_session_id}-{user_id}-{uuid.uuid4()}"
        trace_id = langfuse.create_trace_id(seed=trace_seed)
    else:
        trace_id = str(uuid.uuid4())
    
    # Load conversation history from database (includes the user message that was just saved)
    conversation_history = load_conversation_history(chat_session_id)
    
    # Check if the last message is the current user message (to avoid duplication)
    last_message = conversation_history[-1] if conversation_history else None
    if last_message and isinstance(last_message, HumanMessage) and last_message.content == message:
        # User message already in history, use it as-is
        all_messages = conversation_history
        logger.debug(f"Loaded {len(conversation_history)} messages (including current user message)")
    else:
        # User message not in history yet (shouldn't happen, but handle it)
        new_user_message = HumanMessage(content=message)
        all_messages = conversation_history + [new_user_message]
        logger.debug(f"Loaded {len(conversation_history)} previous messages, adding new user message (total: {len(all_messages)} messages)")
    
    # Prepare initial state
    # Mark execution_type as "streaming" so nodes skip saving (streaming function handles saving)
    initial_state: AgentState = {
        "messages": all_messages,
        "current_agent": None,
        "chat_session_id": chat_session_id,
        "user_id": user_id,
        "tool_calls": [],
        "metadata": {
            "trace_id": trace_id,
            "execution_type": "streaming",  # Mark as streaming to skip saving in nodes
        },
        "next_agent": None,
    }
    
    # Get checkpoint config
    config = get_checkpoint_config(chat_session_id)
    
    # Add Langfuse callback to config if enabled
    if LANGFUSE_ENABLED:
        callback_handler = get_callback_handler()
        if callback_handler:
            # Add callback to config - LangGraph expects callbacks at top level
            if isinstance(config, dict):
                if 'callbacks' not in config:
                    config['callbacks'] = []
                # Add callback if not already present
                if callback_handler not in config['callbacks']:
                    config['callbacks'].append(callback_handler)
                # Also ensure configurable exists for thread_id
                if 'configurable' not in config:
                    config['configurable'] = {}
            else:
                if not hasattr(config, 'callbacks') or config.callbacks is None:
                    config.callbacks = []
                if callback_handler not in config.callbacks:
                    config.callbacks.append(callback_handler)
                if not hasattr(config, 'configurable') or config.configurable is None:
                    config.configurable = {}
    
    try:
        logger.info(f"Streaming agent events for user {user_id}, session {chat_session_id}, trace: {trace_id}")
        
        # Prepare trace context for propagate_attributes
        trace_context = prepare_trace_context(
            user_id=user_id,
            session_id=chat_session_id,
            metadata={
                "chat_session_id": chat_session_id,
                "execution_type": "streaming",
                "trace_id": trace_id,
            }
        )
        
        # Use checkpoint saver as context manager
        with get_checkpoint_saver() as checkpoint_saver:
            # Create graph with checkpoint
            graph = create_agent_graph(checkpoint_saver=checkpoint_saver)
            
            # Stream using LangGraph's native streaming with stream_mode=["messages", "updates"]
            # "messages" streams LLM tokens, "updates" streams state updates
            # This automatically creates the proper chain structure (supervisor → greeter → LLM)
            accumulated_content = ""
            tokens_used = 0
            input_tokens = 0
            output_tokens = 0
            cached_tokens = 0
            final_state = None
            selected_agent_name = None
            
            if LANGFUSE_ENABLED:
                with propagate_attributes(**trace_context):
                    # Stream graph execution with both messages and updates modes
                    # When using multiple modes, events are tuples: (mode, data)
                    for event in graph.stream(
                        initial_state,
                        config=config,
                        stream_mode=["messages", "updates"]
                    ):
                        # event is a tuple: (mode, data) when using multiple stream modes
                        if isinstance(event, tuple) and len(event) == 2:
                            mode, data = event
                            
                            if mode == "messages":
                                # data is a tuple: (message_chunk, metadata)
                                if isinstance(data, tuple) and len(data) == 2:
                                    message_chunk, metadata = data
                                    
                                    # Only stream tokens from agent nodes (greeter, agent), not supervisor
                                    node_name = metadata.get("langgraph_node", "")
                                    if node_name in ["greeter", "agent"]:
                                        if message_chunk and hasattr(message_chunk, 'content'):
                                            chunk_content = message_chunk.content or ""
                                            if chunk_content:
                                                # Handle incremental content (OpenAI streaming format)
                                                if chunk_content.startswith(accumulated_content):
                                                    delta = chunk_content[len(accumulated_content):]
                                                    if delta:
                                                        accumulated_content = chunk_content
                                                        yield {"type": "token", "data": delta}
                                                else:
                                                    # New content chunk
                                                    accumulated_content += chunk_content
                                                    yield {"type": "token", "data": chunk_content}
                                    
                                    # Extract token usage from message chunk if available
                                    if hasattr(message_chunk, 'usage_metadata') and message_chunk.usage_metadata:
                                        usage = message_chunk.usage_metadata
                                        tokens_used = usage.get('total_tokens', 0)
                                        input_tokens = usage.get('input_tokens', 0)
                                        output_tokens = usage.get('output_tokens', 0)
                                        cached_tokens = usage.get('cached_tokens', 0) or usage.get('cached_input_tokens', 0) or usage.get('cache_creation_input_tokens', 0)
                            
                            elif mode == "updates":
                                # data is a dict with state updates
                                if isinstance(data, dict):
                                    # Track current agent and final state
                                    if "current_agent" in data:
                                        selected_agent_name = data.get("current_agent")
                                    # Keep track of final state
                                    final_state = data
            else:
                # Non-Langfuse path
                for event in graph.stream(
                    initial_state,
                    config=config,
                    stream_mode=["messages", "updates"]
                ):
                    if isinstance(event, tuple) and len(event) == 2:
                        mode, data = event
                        
                        if mode == "messages":
                            if isinstance(data, tuple) and len(data) == 2:
                                message_chunk, metadata = data
                                
                                node_name = metadata.get("langgraph_node", "")
                                if node_name in ["greeter", "agent"]:
                                    if message_chunk and hasattr(message_chunk, 'content'):
                                        chunk_content = message_chunk.content or ""
                                        if chunk_content:
                                            if chunk_content.startswith(accumulated_content):
                                                delta = chunk_content[len(accumulated_content):]
                                                if delta:
                                                    accumulated_content = chunk_content
                                                    yield {"type": "token", "data": delta}
                                            else:
                                                accumulated_content += chunk_content
                                                yield {"type": "token", "data": chunk_content}
                        
                        elif mode == "updates":
                            if isinstance(data, dict):
                                if "current_agent" in data:
                                    selected_agent_name = data.get("current_agent")
                                final_state = data
            
            # Extract agent name from final state or use default
            if not selected_agent_name:
                # Try to get from final state or use greeter as default
                selected_agent_name = "greeter"
        
        # Extract token usage from final state if not already captured from streaming chunks
        if tokens_used == 0 and accumulated_content and final_state:
            # Try to get from final state metadata
            if "metadata" in final_state:
                token_usage = final_state["metadata"].get("token_usage", {})
                if token_usage:
                    tokens_used = token_usage.get('total_tokens', 0)
                    input_tokens = token_usage.get('input_tokens', 0) or token_usage.get('prompt_tokens', 0)
                    output_tokens = token_usage.get('output_tokens', 0) or token_usage.get('completion_tokens', 0)
                    cached_tokens = token_usage.get('cached_tokens', 0)
        
        # If still no token usage, try to get from the last message in final state
        if tokens_used == 0 and final_state and "messages" in final_state:
            messages = final_state["messages"]
            if messages:
                last_msg = messages[-1]
                if hasattr(last_msg, 'usage_metadata') and last_msg.usage_metadata:
                    usage = last_msg.usage_metadata
                    tokens_used = usage.get('total_tokens', 0)
                    input_tokens = usage.get('input_tokens', 0)
                    output_tokens = usage.get('output_tokens', 0)
                    cached_tokens = usage.get('cached_tokens', 0) or usage.get('cached_input_tokens', 0) or usage.get('cache_creation_input_tokens', 0)
                elif hasattr(last_msg, 'response_metadata') and last_msg.response_metadata:
                    usage = last_msg.response_metadata.get('token_usage', {})
                    if usage:
                        tokens_used = usage.get('total_tokens', 0)
                        input_tokens = usage.get('prompt_tokens', 0) or usage.get('input_tokens', 0)
                        output_tokens = usage.get('completion_tokens', 0) or usage.get('output_tokens', 0)
                        cached_tokens = usage.get('cached_tokens', 0)
        
        # Save final message to database
        if accumulated_content and chat_session_id:
            try:
                from app.db.models.session import ChatSession
                from app.db.models.message import Message as MessageModel
                from app.agents.config import OPENAI_MODEL
                
                session = ChatSession.objects.get(id=chat_session_id)
                
                if not session.model_used:
                    session.model_used = OPENAI_MODEL
                    session.save(update_fields=['model_used'])
                
                message_obj = MessageModel.objects.create(
                    session=session,
                    role="assistant",
                    content=accumulated_content,
                    tokens_used=tokens_used,
                    metadata={
                        "agent_name": selected_agent_name or "greeter",
                        "tool_calls": [],
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "cached_tokens": cached_tokens,
                        "model": OPENAI_MODEL,
                    }
                )
                
                if tokens_used > 0:
                    session.tokens_used += tokens_used
                    session.save(update_fields=['tokens_used', 'model_used'])
                    
                    from django.contrib.auth import get_user_model
                    User = get_user_model()
                    user = User.objects.get(id=user_id)
                    user.token_usage_count += tokens_used
                    user.save(update_fields=['token_usage_count'])
                
                logger.debug(f"Saved streamed message to database, tokens: {tokens_used}")
            except Exception as e:
                logger.error(f"Error saving streamed message: {e}", exc_info=True)
        
        # Flush traces if Langfuse is enabled
        if LANGFUSE_ENABLED:
            flush_traces()
        
        # Yield completion event
        yield {
            "type": "done",
            "data": {
                "final_text": accumulated_content,
                "tokens_used": tokens_used,
                "trace_id": trace_id,
            }
        }
        
    except Exception as e:
        logger.error(
            f"Error streaming agent events for user {user_id}, session {chat_session_id}: {e}",
            exc_info=True
        )
        
        if LANGFUSE_ENABLED:
            flush_traces()
        
        yield {
            "type": "error",
            "data": {
                "error": str(e),
                "trace_id": trace_id,
            }
        }
