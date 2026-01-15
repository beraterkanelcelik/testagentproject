"""
Agent execution tasks for LangGraph Functional API.
"""
from typing import List, Optional
from langgraph.func import task
from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from app.agents.functional.models import AgentResponse, ToolResult
from app.agents.registry import get_agent
from app.agents.config import OPENAI_MODEL
from app.core.logging import get_logger
from app.agents.context_usage import calculate_context_usage

logger = get_logger(__name__)


def _extract_token_usage(response) -> dict:
    """Extract token usage from AI response."""
    token_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    
    if hasattr(response, 'usage_metadata') and response.usage_metadata:
        usage = response.usage_metadata
        token_usage = {
            "input_tokens": usage.get('input_tokens', 0),
            "output_tokens": usage.get('output_tokens', 0),
            "total_tokens": usage.get('total_tokens', 0),
        }
    elif hasattr(response, 'response_metadata') and response.response_metadata:
        usage = response.response_metadata.get('token_usage', {})
        if usage:
            token_usage = {
                "input_tokens": usage.get('prompt_tokens', 0) or usage.get('input_tokens', 0),
                "output_tokens": usage.get('completion_tokens', 0) or usage.get('output_tokens', 0),
                "total_tokens": usage.get('total_tokens', 0),
            }
    
    return token_usage


def _extract_tool_calls(response) -> List[dict]:
    """Extract tool calls from AI response."""
    tool_calls = []
    
    if hasattr(response, 'tool_calls') and response.tool_calls:
        for tc in response.tool_calls:
            tool_calls.append({
                "tool": tc.get("name", ""),
                "name": tc.get("name", ""),
                "args": tc.get("args", {}),
                "id": tc.get("id", ""),
            })
    
    return tool_calls


@task
def execute_agent(
    agent_name: str,
    messages: List[BaseMessage],
    user_id: Optional[int],
    model_name: Optional[str] = None,
    config: Optional[RunnableConfig] = None
) -> AgentResponse:
    """
    Execute agent with messages.
    
    Args:
        agent_name: Name of agent to execute
        messages: Conversation history
        user_id: User ID
        model_name: Optional model name
        config: Optional runtime config (for callbacks)
        
    Returns:
        AgentResponse with reply and tool calls
    """
    try:
        logger.info(f"[EXECUTE_AGENT] Starting {agent_name} agent with {len(messages)} messages")
        
        # Get agent from registry
        agent = get_agent(agent_name, user_id, model_name or OPENAI_MODEL)
        
        # Check if summarization is needed
        from app.agents.functional.tasks.common import check_summarization_needed_task
        needs_summarization = check_summarization_needed_task(
            messages=messages,
            token_threshold=40000,
            model_name=model_name
        ).result()
        
        # Trim messages if approaching context limit using LangChain's trim_messages
        from app.agents.context_usage import get_trimmed_messages, calculate_context_usage
        context_usage = calculate_context_usage(messages, model_name or OPENAI_MODEL)
        
        # Trim if usage exceeds 80% of context window
        if context_usage.get("usage_percentage", 0) > 80.0:
            logger.info(f"Context usage {context_usage['usage_percentage']:.1f}% exceeds 80%, trimming messages")
            messages = get_trimmed_messages(
                messages=messages,
                model_name=model_name or OPENAI_MODEL,
                include_system=True,
                strategy="last"
            )
        
        # Apply summarization middleware if needed (alternative to trimming)
        if needs_summarization:
            from app.agents.functional.middleware import create_agent_with_summarization
            from app.agents.functional.workflow import get_sync_checkpointer

            checkpointer = get_sync_checkpointer()
            if checkpointer:
                agent = create_agent_with_summarization(
                    agent=agent,
                    model_name=model_name or OPENAI_MODEL,
                    checkpointer=checkpointer
                )
                logger.info(f"Applied SummarizationMiddleware to {agent_name} agent")
        
        # Invoke agent
        invoke_kwargs = {}
        if config:
            invoke_kwargs['config'] = config
        
        logger.info(f"[EXECUTE_AGENT] Invoking {agent_name} agent")
        
        # Record metrics
        import time
        start_time = time.time()
        try:
            response = agent.invoke(messages, **invoke_kwargs)
            duration = time.time() - start_time
            
            # Record success metrics
            try:
                from app.observability.metrics import record_agent_request
                record_agent_request(agent_name, duration, status="success")
            except Exception as e:
                logger.warning(f"Failed to record metrics: {e}")
        except Exception as e:
            duration = time.time() - start_time
            # Record error metrics
            try:
                from app.observability.metrics import record_agent_request, record_error
                record_agent_request(agent_name, duration, status="error")
                record_error(agent_name, type(e).__name__)
            except Exception:
                pass
            raise
        
        # Extract token usage and tool calls
        token_usage = _extract_token_usage(response)
        tool_calls = _extract_tool_calls(response)
        
        # Recalculate context usage with final messages (after trimming)
        context_usage = calculate_context_usage(messages, model_name or OPENAI_MODEL)
        
        # Record context usage metrics
        try:
            from app.observability.metrics import record_context_usage
            record_context_usage(model_name or OPENAI_MODEL, context_usage.get("usage_percentage", 0))
        except Exception:
            pass
        
        reply_content = response.content if hasattr(response, 'content') else str(response)
        
        agent_response = AgentResponse(
            type="answer",
            reply=reply_content,
            tool_calls=tool_calls,
            token_usage=token_usage,
            agent_name=agent.name,
            context_usage=context_usage
        )
        
        logger.info(f"[EXECUTE_AGENT] {agent_name} completed: context={context_usage['usage_percentage']}%")
        return agent_response
        
    except Exception as e:
        logger.error(f"[EXECUTE_AGENT] Error in {agent_name} agent: {e}", exc_info=True)
        return AgentResponse(
            type="answer",
            reply=f"I apologize, but I encountered an error: {str(e)}",
            agent_name=agent_name
        )


@task
def refine_with_tool_results(
    agent_name: str,
    messages: List[BaseMessage],
    tool_results: List[ToolResult],
    user_id: Optional[int],
    model_name: Optional[str] = None,
    config: Optional[RunnableConfig] = None
) -> AgentResponse:
    """
    Refine agent response with tool results.
    
    Args:
        agent_name: Name of agent to use
        messages: Conversation history (should include tool results as ToolMessages)
        tool_results: List of tool execution results
        user_id: User ID
        model_name: Optional model name
        config: Optional runtime config (for callbacks)
        
    Returns:
        AgentResponse with refined answer
    """
    try:
        logger.info(f"[REFINE] Starting for agent={agent_name}, messages_count={len(messages)}, tool_results_count={len(tool_results)}")
        
        # Use execute_agent to process with tool results
        result = execute_agent(
            agent_name=agent_name,
            messages=messages,
            user_id=user_id,
            model_name=model_name,
            config=config
        ).result()
        
        logger.info(f"[REFINE] Agent task returned: has_reply={bool(result.reply)}")
        return result
        
    except Exception as e:
        logger.error(f"Error in refine_with_tool_results: {e}", exc_info=True)
        return AgentResponse(
            type="answer",
            reply=f"I apologize, but I encountered an error processing tool results: {str(e)}",
            agent_name=agent_name
        )
