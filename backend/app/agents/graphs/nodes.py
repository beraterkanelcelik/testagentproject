"""
Graph node implementations.
"""
from typing import Dict, Any, Iterator
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from app.agents.graphs.state import AgentState
from app.agents.agents.supervisor import SupervisorAgent
from app.agents.agents.greeter import GreeterAgent
from app.agents.tools.registry import tool_registry
from app.db.models.message import Message as MessageModel
from app.db.models.session import ChatSession
from app.core.logging import get_logger

logger = get_logger(__name__)

supervisor_agent = SupervisorAgent()
greeter_agent = GreeterAgent()


def supervisor_node(state: AgentState) -> AgentState:
    """
    Supervisor node - main entry point that analyzes the message.
    
    Args:
        state: Current graph state
        
    Returns:
        Updated state
    """
    messages = state.get("messages", [])
    
    if not messages:
        return state
    
    # Set current agent
    state["current_agent"] = "supervisor"
    
    # Supervisor analyzes but doesn't respond directly
    # Routing happens in router function
    return state


def greeter_node(state: AgentState) -> AgentState:
    """
    Greeter node - executes greeter agent.
    
    Args:
        state: Current graph state
        
    Returns:
        Updated state with greeter response
    """
    messages = state.get("messages", [])
    
    if not messages:
        return state
    
    state["current_agent"] = "greeter"
    
    try:
        logger.debug("Executing greeter node")
        # Get greeter response
        response = greeter_agent.invoke(messages)
        
        # Extract token usage from response if available
        tokens_used = 0
        input_tokens = 0
        output_tokens = 0
        cached_tokens = 0
        
        if hasattr(response, 'response_metadata') and response.response_metadata:
            usage = response.response_metadata.get('token_usage', {})
            if usage:
                tokens_used = usage.get('total_tokens', 0)
                input_tokens = usage.get('prompt_tokens', 0)
                output_tokens = usage.get('completion_tokens', 0)
                cached_tokens = usage.get('cached_tokens', 0)
                state["metadata"]["token_usage"] = usage
                logger.info(f"Token usage extracted from greeter response: {tokens_used} total tokens (input: {input_tokens}, output: {output_tokens}, cached: {cached_tokens})")
            else:
                logger.warning("response_metadata exists but token_usage is missing")
        else:
            logger.warning(f"Response metadata not available. Has response_metadata: {hasattr(response, 'response_metadata')}, response_metadata value: {getattr(response, 'response_metadata', None)}")
        
        # Add response to messages
        if isinstance(response, AIMessage):
            state["messages"].append(response)
        else:
            # Wrap in AIMessage if needed
            state["messages"].append(AIMessage(content=str(response.content)))
        
        # Save message to database if chat_session_id exists
        chat_session_id = state.get("chat_session_id")
        if chat_session_id:
            try:
                session = ChatSession.objects.get(id=chat_session_id)
                from app.agents.config import OPENAI_MODEL
                
                # Update model_used if not set
                if not session.model_used:
                    session.model_used = OPENAI_MODEL
                
                message_obj = MessageModel.objects.create(
                    session=session,
                    role="assistant",
                    content=response.content if hasattr(response, 'content') else str(response),
                    tokens_used=tokens_used,
                    metadata={
                        "agent_name": "greeter",
                        "tool_calls": state.get("tool_calls", []),
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
                    
                    user = session.user
                    user.token_usage_count += tokens_used
                    user.save(update_fields=['token_usage_count'])
                
                logger.debug(f"Saved greeter message to database for session {chat_session_id}, tokens: {tokens_used}")
            except ChatSession.DoesNotExist:
                logger.warning(f"Chat session {chat_session_id} not found when saving message")
            except Exception as e:
                logger.error(f"Error saving greeter message to database: {e}", exc_info=True)
        
    except Exception as e:
        logger.error(f"Error in greeter node: {e}", exc_info=True)
        # On error, add error message
        error_msg = AIMessage(content=f"I apologize, but I encountered an error: {str(e)}")
        state["messages"].append(error_msg)
    
    return state


def agent_node(state: AgentState) -> AgentState:
    """
    Generic agent node - executes the agent specified in next_agent.
    For now, this is a placeholder for future agents.
    
    Args:
        state: Current graph state
        
    Returns:
        Updated state
    """
    messages = state.get("messages", [])
    next_agent_name = state.get("next_agent", "greeter")
    
    if not messages:
        return state
    
    state["current_agent"] = next_agent_name
    
    # For now, route unknown agents to greeter
    # In future, we can have specific agent implementations here
    if next_agent_name == "gmail":
        # Placeholder for Gmail agent (to be implemented)
        response = AIMessage(
            content="Gmail agent is not yet implemented. This feature will be available soon."
        )
        tokens_used = 0
    else:
        # Default to greeter
        response = greeter_agent.invoke(messages)
        if not isinstance(response, AIMessage):
            response = AIMessage(content=str(response.content))
        
        # Extract token usage from response if available
        tokens_used = 0
        input_tokens = 0
        output_tokens = 0
        cached_tokens = 0
        
        if hasattr(response, 'response_metadata') and response.response_metadata:
            usage = response.response_metadata.get('token_usage', {})
            if usage:
                tokens_used = usage.get('total_tokens', 0)
                input_tokens = usage.get('prompt_tokens', 0)
                output_tokens = usage.get('completion_tokens', 0)
                cached_tokens = usage.get('cached_tokens', 0)
                state["metadata"]["token_usage"] = usage
    
    state["messages"].append(response)
    
    # Save to database
    chat_session_id = state.get("chat_session_id")
    if chat_session_id:
        try:
            session = ChatSession.objects.get(id=chat_session_id)
            from app.agents.config import OPENAI_MODEL
            
            # Update model_used if not set
            if not session.model_used:
                session.model_used = OPENAI_MODEL
            
            message_obj = MessageModel.objects.create(
                session=session,
                role="assistant",
                content=response.content if hasattr(response, 'content') else str(response),
                tokens_used=tokens_used,
                metadata={
                    "agent_name": next_agent_name,
                    "tool_calls": state.get("tool_calls", []),
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
                
                user = session.user
                user.token_usage_count += tokens_used
                user.save(update_fields=['token_usage_count'])
            
            logger.debug(f"Saved agent message to database for session {chat_session_id}, tokens: {tokens_used}")
        except ChatSession.DoesNotExist:
            logger.warning(f"Chat session {chat_session_id} not found when saving message")
        except Exception as e:
            logger.error(f"Error saving agent message to database: {e}", exc_info=True)
    
    return state


def tool_node(state: AgentState) -> AgentState:
    """
    Tool execution node - executes tools when needed.
    
    Args:
        state: Current graph state
        
    Returns:
        Updated state with tool results
    """
    messages = state.get("messages", [])
    current_agent = state.get("current_agent", "supervisor")
    
    if not messages:
        return state
    
    # Get last message (should be AIMessage with tool calls)
    last_message = messages[-1] if messages else None
    
    if not last_message or not hasattr(last_message, 'tool_calls') or not last_message.tool_calls:
        return state
    
    # Get tools for current agent
    tools = tool_registry.get_tools_for_agent(current_agent)
    tool_map = {tool.name: tool for tool in tools}
    
    # Execute tool calls
    tool_results = []
    for tool_call in last_message.tool_calls:
        tool_name = tool_call.get("name")
        tool_args = tool_call.get("args", {})
        
        if tool_name in tool_map:
            try:
                logger.debug(f"Executing tool {tool_name} with args {tool_args}")
                result = tool_map[tool_name].invoke(tool_args)
                tool_results.append({
                    "tool": tool_name,
                    "result": result,
                })
                state["tool_calls"].append({
                    "tool": tool_name,
                    "args": tool_args,
                    "result": result,
                })
                logger.debug(f"Tool {tool_name} executed successfully")
            except Exception as e:
                logger.error(f"Error executing tool {tool_name}: {e}", exc_info=True)
                tool_results.append({
                    "tool": tool_name,
                    "error": str(e),
                })
    
    # Add tool results to state metadata
    state["metadata"]["tool_results"] = tool_results
    
    return state
