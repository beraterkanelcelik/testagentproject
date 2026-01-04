"""
Agent graph execution and event streaming.
"""
import uuid
import os
from typing import Dict, Any, Iterator, Optional
from langchain_core.messages import HumanMessage, AIMessage
from app.agents.graphs.graph import create_agent_graph
from app.agents.graphs.state import AgentState
from app.agents.checkpoint import get_checkpoint_config, get_checkpoint_saver
from app.agents.config import MAX_ITERATIONS, LANGCHAIN_TRACING_V2, LANGCHAIN_PROJECT
from app.agents.agents.greeter import GreeterAgent
from app.core.logging import get_logger

logger = get_logger(__name__)

# Enable LangSmith tracing if configured
if LANGCHAIN_TRACING_V2:
    os.environ['LANGCHAIN_TRACING_V2'] = 'true'
    os.environ['LANGCHAIN_PROJECT'] = LANGCHAIN_PROJECT

greeter_agent = GreeterAgent()


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
    
    # Get checkpoint config
    config = get_checkpoint_config(chat_session_id)
    
    # Prepare initial state
    initial_state: AgentState = {
        "messages": [HumanMessage(content=message)],
        "current_agent": None,
        "chat_session_id": chat_session_id,
        "user_id": user_id,
        "tool_calls": [],
        "metadata": {},
        "next_agent": None,
    }
    
    # Execute graph with checkpoint context
    try:
        logger.info(f"Executing agent for user {user_id}, session {chat_session_id}")
        
        # Use checkpoint saver as context manager
        with get_checkpoint_saver() as checkpoint_saver:
            # Create graph with checkpoint
            graph = create_agent_graph(checkpoint_saver=checkpoint_saver)
            
            # Execute graph
            final_state = graph.invoke(initial_state, config=config)
            
            # Extract final response
            messages = final_state.get("messages", [])
            last_message = messages[-1] if messages else None
            
            response_text = ""
            if isinstance(last_message, AIMessage):
                response_text = last_message.content
            
            logger.info(f"Agent execution completed successfully. Agent: {final_state.get('current_agent')}")
            
            return {
                "success": True,
                "response": response_text,
                "agent": final_state.get("current_agent"),
                "tool_calls": final_state.get("tool_calls", []),
            }
    except Exception as e:
        logger.error(
            f"Error executing agent for user {user_id}, session {chat_session_id}: {e}",
            exc_info=True
        )
        return {
            "success": False,
            "error": str(e),
            "response": f"I apologize, but I encountered an error: {str(e)}",
        }


def stream_agent_events(
    user_id: int,
    chat_session_id: int,
    message: str
) -> Iterator[Dict[str, Any]]:
    """
    Stream agent execution events token-by-token.
    
    Args:
        user_id: User ID
        chat_session_id: Chat session ID
        message: User message
        
    Yields:
        Event dictionaries with type and data
    """
    from app.agents.checkpoint import get_checkpoint_saver
    from app.agents.graphs.routers import route_message
    
    # Get checkpoint config
    config = get_checkpoint_config(chat_session_id)
    
    # Prepare initial state
    initial_state: AgentState = {
        "messages": [HumanMessage(content=message)],
        "current_agent": None,
        "chat_session_id": chat_session_id,
        "user_id": user_id,
        "tool_calls": [],
        "metadata": {},
        "next_agent": None,
    }
    
    try:
        logger.info(f"Streaming agent events for user {user_id}, session {chat_session_id}")
        
        # Determine which agent to use (simplified routing)
        # In a real implementation, you'd use the supervisor graph
        # For now, we'll use greeter agent directly for streaming
        messages = [HumanMessage(content=message)]
        
        # Stream from greeter agent token-by-token
        # With stream_usage=True, token usage is available in usage_metadata of the final chunk
        accumulated_content = ""
        tokens_used = 0
        final_chunk = None
        
        # Prepare messages with system prompt
        system_prompt = greeter_agent.get_system_prompt()
        if system_prompt:
            from langchain_core.messages import SystemMessage
            full_messages = [SystemMessage(content=system_prompt)] + messages
        else:
            full_messages = messages
        
        # Stream responses - collect all chunks to find the one with usage_metadata
        chunks = []
        for chunk in greeter_agent.llm.stream(full_messages):
            chunks.append(chunk)
            
            # Chunk is an AIMessage chunk
            if hasattr(chunk, 'content'):
                chunk_content = chunk.content or ""
                
                if chunk_content:
                    # Check if this is accumulated content or delta
                    if chunk_content.startswith(accumulated_content):
                        # This is accumulated content, extract delta
                        delta = chunk_content[len(accumulated_content):]
                        if delta:
                            accumulated_content = chunk_content
                            yield {
                                "type": "token",
                                "data": delta,  # Send only the new tokens
                            }
                    else:
                        # This is delta content, accumulate it
                        accumulated_content += chunk_content
                        yield {
                            "type": "token",
                            "data": chunk_content,  # Send the delta
                        }
        
        # Extract token usage from chunks
        # With stream_usage=True, the chunk with finish_reason contains usage_metadata
        input_tokens = 0
        output_tokens = 0
        cached_tokens = 0
        
        for chunk in chunks:
            # Check for finish_reason in response_metadata (indicates final chunk with usage)
            if hasattr(chunk, 'response_metadata') and chunk.response_metadata:
                if 'finish_reason' in chunk.response_metadata:
                    # This is the final chunk - check for usage_metadata
                    if hasattr(chunk, 'usage_metadata') and chunk.usage_metadata:
                        usage = chunk.usage_metadata
                        tokens_used = usage.get('total_tokens', 0)
                        input_tokens = usage.get('input_tokens', 0)
                        output_tokens = usage.get('output_tokens', 0)
                        # Cached tokens might be in different fields
                        cached_tokens = usage.get('cached_tokens', 0) or usage.get('cached_input_tokens', 0) or usage.get('cache_creation_input_tokens', 0)
                        logger.info(f"Token usage from usage_metadata (finish_reason chunk): {tokens_used} total tokens (input: {input_tokens}, output: {output_tokens}, cached: {cached_tokens})")
                        break
                    # Fallback: check response_metadata for usage
                    elif 'usage' in chunk.response_metadata:
                        usage = chunk.response_metadata.get('usage', {})
                        tokens_used = usage.get('total_tokens', 0)
                        input_tokens = usage.get('prompt_tokens', 0)  # OpenAI uses prompt_tokens
                        output_tokens = usage.get('completion_tokens', 0)
                        cached_tokens = usage.get('cached_tokens', 0)
                        logger.info(f"Token usage from response_metadata.usage (finish_reason chunk): {tokens_used} total tokens")
                        break
                    elif 'token_usage' in chunk.response_metadata:
                        usage = chunk.response_metadata.get('token_usage', {})
                        tokens_used = usage.get('total_tokens', 0)
                        input_tokens = usage.get('prompt_tokens', 0)
                        output_tokens = usage.get('completion_tokens', 0)
                        cached_tokens = usage.get('cached_tokens', 0)
                        logger.info(f"Token usage from response_metadata.token_usage (finish_reason chunk): {tokens_used} total tokens")
                        break
            
            # Also check usage_metadata in any chunk (in case it's not the finish_reason one)
            if hasattr(chunk, 'usage_metadata') and chunk.usage_metadata:
                usage = chunk.usage_metadata
                tokens_used = usage.get('total_tokens', 0)
                input_tokens = usage.get('input_tokens', 0)
                output_tokens = usage.get('output_tokens', 0)
                # Cached tokens might be in different fields
                cached_tokens = usage.get('cached_tokens', 0) or usage.get('cached_input_tokens', 0) or usage.get('cache_creation_input_tokens', 0)
                logger.info(f"Token usage from usage_metadata: {tokens_used} total tokens (input: {input_tokens}, output: {output_tokens}, cached: {cached_tokens})")
                break
        
        # If we didn't get separate I/O tokens, use total_tokens as output (for assistant messages)
        if tokens_used > 0 and input_tokens == 0 and output_tokens == 0:
            # For assistant messages, most tokens are output
            # This is a fallback - ideally we should have I/O breakdown
            output_tokens = tokens_used
            logger.warning("I/O token breakdown not available, using total_tokens as output_tokens")
        
        if tokens_used == 0:
            # No token usage found - log debug info
            logger.warning(f"Token usage not found in any chunk. Total chunks: {len(chunks)}")
            if chunks:
                for i, chunk in enumerate(chunks):
                    logger.debug(f"Chunk {i} type: {type(chunk)}")
                    if hasattr(chunk, 'response_metadata') and chunk.response_metadata:
                        logger.debug(f"Chunk {i} response_metadata: {chunk.response_metadata}")
                    if hasattr(chunk, 'usage_metadata'):
                        logger.debug(f"Chunk {i} usage_metadata: {chunk.usage_metadata}")
                    if hasattr(chunk, 'content'):
                        logger.debug(f"Chunk {i} content length: {len(chunk.content) if chunk.content else 0}")
        
        # Save final message to database
        if accumulated_content and chat_session_id:
            try:
                from app.db.models.session import ChatSession
                from app.db.models.message import Message as MessageModel
                from app.agents.config import OPENAI_MODEL
                
                session = ChatSession.objects.get(id=chat_session_id)
                
                # Update model_used if not set
                if not session.model_used:
                    session.model_used = OPENAI_MODEL
                    session.save(update_fields=['model_used'])
                
                message_obj = MessageModel.objects.create(
                    session=session,
                    role="assistant",
                    content=accumulated_content,
                    tokens_used=tokens_used,
                    metadata={
                        "agent_name": "greeter",  # Currently using greeter for streaming
                        "tool_calls": [],
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "cached_tokens": cached_tokens,
                        "model": OPENAI_MODEL,
                    }
                )
                
                # Update session and user token usage
                if tokens_used > 0:
                    session.tokens_used += tokens_used
                    session.save(update_fields=['tokens_used', 'model_used'])
                    
                    from django.contrib.auth import get_user_model
                    User = get_user_model()
                    user = User.objects.get(id=user_id)
                    user.token_usage_count += tokens_used
                    user.save(update_fields=['token_usage_count'])
                
                logger.debug(f"Saved streamed message to database, tokens: {tokens_used} (input: {input_tokens}, output: {output_tokens}, cached: {cached_tokens})")
            except Exception as e:
                logger.error(f"Error saving streamed message: {e}", exc_info=True)
        
        # Yield completion event
        yield {
            "type": "done",
            "data": {
                "final_text": accumulated_content,
                "tokens_used": tokens_used,
            }
        }
        
    except Exception as e:
        logger.error(
            f"Error streaming agent events for user {user_id}, session {chat_session_id}: {e}",
            exc_info=True
        )
        yield {
            "type": "error",
            "data": {
                "error": str(e),
            }
        }
