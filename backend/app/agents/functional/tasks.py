"""
Task functions for LangGraph Functional API.
"""
import asyncio
import json
from typing import List, Dict, Any, Optional
from langgraph.func import task
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from app.agents.functional.models import AgentResponse, RoutingDecision, ToolResult
from app.agents.agents.supervisor import SupervisorAgent
from app.agents.registry import get_agent  # Use generic agent registry
from app.services.chat_service import get_messages, add_message
from app.db.models.session import ChatSession
from app.agents.config import OPENAI_MODEL
from app.core.logging import get_logger
from app.rag.chunking.tokenizer import count_tokens
from app.agents.context_usage import calculate_context_usage

logger = get_logger(__name__)

supervisor_agent = SupervisorAgent()

# Maximum size for tool outputs before truncation (50KB)
MAX_TOOL_OUTPUT_SIZE = 50_000


def truncate_tool_output(output: Any) -> Any:
    """
    Truncate large tool outputs to prevent unbounded memory growth.
    
    Args:
        output: Tool output (any type)
        
    Returns:
        Truncated output if too large, original output otherwise
    """
    try:
        serialized = json.dumps(output, default=str)
        if len(serialized) > MAX_TOOL_OUTPUT_SIZE:
            return {
                "truncated": True,
                "preview": serialized[:1000],
                "size": len(serialized),
                "original_size": len(serialized)
            }
        return output
    except Exception as e:
        logger.warning(f"Error truncating tool output: {e}")
        # If serialization fails, return a safe representation
        return {"error": "Failed to serialize tool output", "type": str(type(output))}


@task
def supervisor_task(
    query: str,
    messages: List[BaseMessage],
    config: Optional[RunnableConfig] = None
) -> RoutingDecision:
    """
    Route user query to appropriate domain agent.
    
    Args:
        query: User query
        messages: Conversation history as LangChain messages
        config: Optional runtime config (for callbacks)
        
    Returns:
        RoutingDecision with agent name and query
    """
    try:
        # Use supervisor to determine routing
        invoke_kwargs = {}
        if config:
            invoke_kwargs['config'] = config
        
        agent_name = supervisor_agent.route_message(messages, **invoke_kwargs)
        logger.debug(f"Supervisor routed to agent: {agent_name}")
        
        # Validate and return routing decision
        if not agent_name or agent_name.strip() == "":
            logger.warning("Supervisor returned empty agent name, defaulting to greeter")
            return RoutingDecision(agent="greeter", query=query)
        
        # Map agent names to valid literals
        valid_agents = ["greeter", "gmail", "config", "search", "process"]
        if agent_name not in valid_agents:
            logger.warning(f"Invalid agent name '{agent_name}', defaulting to greeter")
            return RoutingDecision(agent="greeter", query=query)
        
        return RoutingDecision(agent=agent_name, query=query)
    except Exception as e:
        logger.error(f"Error in supervisor_task: {e}", exc_info=True)
        return RoutingDecision(agent="greeter", query=query)


@task
def load_messages_task(
    session_id: Optional[int],
    checkpointer: Any,
    thread_id: str
) -> List[BaseMessage]:
    """
    Load conversation history from checkpoint or database.
    
    Args:
        session_id: Chat session ID
        checkpointer: LangGraph checkpointer instance
        thread_id: Thread ID for checkpoint
        
    Returns:
        List of LangChain BaseMessage objects
    """
    messages = []
    
    # Try to load from checkpoint first
    if checkpointer:
        try:
            checkpoint_config = {"configurable": {"thread_id": thread_id}}
            checkpoint = checkpointer.get(checkpoint_config)
            if checkpoint and "messages" in checkpoint:
                messages = checkpoint["messages"]
                logger.debug(f"Loaded {len(messages)} messages from checkpoint for thread {thread_id}")
                return messages
        except Exception as e:
            logger.warning(f"Failed to load from checkpoint: {e}, falling back to database")
    
    # Fallback to database loading
    if session_id:
        try:
            db_messages = get_messages(session_id)
            
            # Convert to LangChain message format
            for msg in db_messages:
                if msg.role == 'user':
                    messages.append(HumanMessage(content=msg.content))
                elif msg.role == 'assistant':
                    aimessage = AIMessage(content=msg.content)
                    if msg.metadata:
                        aimessage.response_metadata = msg.metadata
                    messages.append(aimessage)
                elif msg.role == 'system':
                    messages.append(SystemMessage(content=msg.content))
            
            logger.debug(f"Loaded {len(messages)} messages from database for session {session_id}")
        except Exception as e:
            logger.error(f"Error loading messages from database: {e}", exc_info=True)
    
    return messages


def _extract_token_usage(response: AIMessage) -> Dict[str, int]:
    """Extract token usage from AI response (reusable helper)"""
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


def _extract_tool_calls(response: AIMessage) -> List[Dict[str, Any]]:
    """Extract tool calls from AI response (reusable helper)"""
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
def generic_agent_task(
    agent_name: str,
    query: str,
    messages: List[BaseMessage],
    user_id: Optional[int],
    model_name: Optional[str] = None,
    config: Optional[RunnableConfig] = None
) -> AgentResponse:
    """
    Generic agent task - works for ANY agent.

    Replaces hardcoded greeter_agent_task, search_agent_task, etc.

    Args:
        agent_name: Name of agent to execute (e.g., "greeter", "search")
        query: User query
        messages: Conversation history
        user_id: User ID for tool access
        model_name: Optional model name
        config: Optional runtime config (for callbacks)

    Returns:
        AgentResponse with reply and context usage
    """
    try:
        logger.info(f"[AGENT_TASK] Starting {agent_name} agent: query_preview={query[:50] if query else '(empty)'}... user_id={user_id}")

        # Get agent from registry (generic!)
        agent = get_agent(agent_name, user_id, model_name or OPENAI_MODEL)

        # Check if summarization is needed
        needs_summarization = check_summarization_needed_task(
            messages=messages,
            token_threshold=40000,
            model_name=model_name
        ).result()

        # Apply summarization middleware if needed
        if needs_summarization:
            from app.agents.functional.middleware import create_agent_with_summarization
            # Reuse the global checkpointer instance instead of creating a new one
            # This follows LangGraph best practices: single checkpointer instance per app
            from app.agents.functional.workflow import get_checkpointer
            
            checkpointer = get_checkpointer()
            if checkpointer:
                agent = create_agent_with_summarization(
                    agent=agent,
                    model_name=model_name or OPENAI_MODEL,
                    checkpointer=checkpointer
                )
                logger.info(f"Applied SummarizationMiddleware to {agent_name} agent")
            else:
                logger.warning(f"Checkpointer not available, skipping summarization middleware for {agent_name}")

        # Add user message if not already in messages
        if not messages or not isinstance(messages[-1], HumanMessage) or messages[-1].content != query:
            messages = messages + [HumanMessage(content=query)]

        # Invoke agent
        invoke_kwargs = {}
        if config:
            invoke_kwargs['config'] = config

        logger.info(f"[AGENT_TASK] Invoking {agent_name} agent with {len(messages)} messages")
        response = agent.invoke(messages, **invoke_kwargs)

        # Extract token usage and tool calls (using helpers)
        token_usage = _extract_token_usage(response)
        tool_calls = _extract_tool_calls(response)

        # Calculate context usage for frontend
        context_usage = calculate_context_usage(messages, model_name or OPENAI_MODEL)

        # Add AIMessage if it has tool_calls
        if hasattr(response, 'tool_calls') and response.tool_calls:
            messages = messages + [response]

        reply_content = response.content if hasattr(response, 'content') else str(response)

        agent_response = AgentResponse(
            type="answer",
            reply=reply_content,
            tool_calls=tool_calls,
            token_usage=token_usage,
            agent_name=agent.name,
            context_usage=context_usage  # NEW: Context usage tracking
        )

        logger.info(f"[AGENT_TASK] {agent_name} completed: context={context_usage['usage_percentage']}%")
        return agent_response

    except Exception as e:
        logger.error(f"[AGENT_TASK] Error in {agent_name} agent: {e}", exc_info=True)
        return AgentResponse(
            type="answer",
            reply=f"I apologize, but I encountered an error: {str(e)}",
            agent_name=agent_name
        )


@task
def agent_task(
    agent_name: str,
    query: str,
    messages: List[BaseMessage],
    user_id: Optional[int],
    tool_results: Optional[List[ToolResult]] = None,
    model_name: Optional[str] = None,
    config: Optional[RunnableConfig] = None
) -> AgentResponse:
    """
    Execute a generic agent (uses registry, no hardcoded routing).
    
    Args:
        agent_name: Name of agent to execute
        query: User query
        messages: Conversation history
        user_id: User ID
        tool_results: Optional tool execution results (currently unused, for future use)
        model_name: Optional model name
        config: Optional runtime config (for callbacks)
        
    Returns:
        AgentResponse with reply
    """
    # Call generic_agent_task and get result (both are @task, so need .result())
    # Note: Don't pass config explicitly - LangGraph auto-injects it for @task functions
    return generic_agent_task(agent_name, query, messages, user_id, model_name).result()


@task
def tool_execution_task(
    tool_calls: List[Dict[str, Any]],
    user_id: Optional[int],
    agent_name: str = "greeter",
    chat_session_id: Optional[int] = None,
    config: Optional[RunnableConfig] = None
) -> List[ToolResult]:
    """
    Execute tools and return results.
    
    Args:
        tool_calls: List of tool call dictionaries with 'name' and 'args'
        user_id: User ID for tool access
        agent_name: Agent name (for tool registry lookup)
        chat_session_id: Optional chat session ID
        config: Optional runtime config (for callbacks)
        
    Returns:
        List of ToolResult objects
    """
    logger.info(f"[TOOL_EXECUTION] Starting execution of {len(tool_calls)} tools for agent={agent_name}: {[tc.get('name') for tc in tool_calls]}")
    """
    Execute tools from tool calls with Langfuse tracking.
    
    Args:
        tool_calls: List of tool call dictionaries with 'name' and 'args'
        user_id: User ID for tool context
        agent_name: Name of agent that has the tools (default: greeter)
        chat_session_id: Chat session ID for tool context
        config: Optional runtime config (for callbacks and Langfuse tracking)
        
    Returns:
        List of ToolResult objects
    """
    from langfuse import get_client
    from app.agents.config import LANGFUSE_ENABLED
    
    results = []
    
    # Get model name from session if available
    model_name = None
    if chat_session_id:
        try:
            session = ChatSession.objects.get(id=chat_session_id)
            if session.model_used:
                model_name = session.model_used
        except ChatSession.DoesNotExist:
            pass
    
    # Get agent for tools using generic registry (no hardcoded agent caches)
    from app.agents.registry import get_agent
    agent = get_agent(agent_name, user_id, model_name)
    
    # Get tools from agent
    tools = agent.get_tools()
    tool_map = {tool.name: tool for tool in tools}
    
    # Get Langfuse client for tracking if enabled
    langfuse = None
    if LANGFUSE_ENABLED:
        try:
            langfuse = get_client()
        except Exception as e:
            logger.warning(f"Failed to get Langfuse client for tool tracking: {e}")
    
    # Execute each tool call with Langfuse tracking
    for tool_call in tool_calls:
        tool_call_id = tool_call.get("id")  # Extract tool_call_id if provided
        tool_name = tool_call.get("name") or tool_call.get("tool")
        tool_args = tool_call.get("args", {})
        
        if not tool_name:
            logger.warning(f"Skipping tool call without name: {tool_call}")
            continue
        
        logger.info(f"Executing tool: {tool_name} with args: {tool_args}, tool_call_id={tool_call_id}")
        
        if tool_name in tool_map:
            tool = tool_map[tool_name]
            
            # Track tool execution with Langfuse
            span = None
            if langfuse:
                try:
                    # Use start_observation() to get the observation object directly
                    span = langfuse.start_observation(
                        as_type="span",
                        name=f"tool_{tool_name}",
                        metadata={
                            "tool_name": tool_name,
                            "agent_name": agent_name,
                            "user_id": str(user_id) if user_id else None,
                            "session_id": str(chat_session_id) if chat_session_id else None,
                        }
                    )
                except Exception as e:
                    logger.warning(f"Failed to create Langfuse span for tool {tool_name}: {e}")
            
            try:
                # Execute tool - if it's a LangChain tool, it might support config
                if hasattr(tool, 'invoke'):
                    if config and hasattr(tool, 'invoke'):
                        # Try to pass config if tool supports it
                        try:
                            result = tool.invoke(tool_args, config=config)
                        except TypeError:
                            # Tool doesn't accept config, invoke without it
                            result = tool.invoke(tool_args)
                    else:
                        result = tool.invoke(tool_args)
                else:
                    result = tool(tool_args)
                
                # Update span with output
                if span:
                    try:
                        span.update(
                            input=tool_args,
                            output=str(result) if result else None,
                        )
                    except Exception as e:
                        logger.warning(f"Failed to update Langfuse span for tool {tool_name}: {e}")
                
                results.append(ToolResult(
                    tool=tool_name,
                    args=tool_args,
                    output=result,
                    error="",
                    tool_call_id=tool_call_id  # Propagate tool_call_id to result
                ))
                output_preview = str(result)[:100] if result else "(empty)"
                logger.info(f"[TOOL_EXECUTION] Tool {tool_name} executed successfully: output_length={len(str(result)) if result else 0}, output_preview={output_preview}...")
            except Exception as e:
                logger.error(f"Error executing tool {tool_name}: {e}", exc_info=True)
                
                # Update span with error
                if span:
                    try:
                        span.update(
                            input=tool_args,
                            output=None,
                            level="ERROR",
                            status_message=str(e)
                        )
                    except Exception:
                        pass
                
                results.append(ToolResult(
                    tool=tool_name,
                    args=tool_args,
                    output=None,
                    error=str(e),
                    tool_call_id=tool_call_id  # Propagate tool_call_id to result even on error
                ))
            finally:
                # End span
                if span:
                    try:
                        span.end()
                    except Exception:
                        pass
        else:
            # Fallback: Try to get tool from registry directly
            logger.warning(f"Tool {tool_name} not found in tool_map for agent={agent_name}, trying tool registry")
            try:
                from app.agents.tools.registry import tool_registry
                tool_instance = tool_registry.get_tool_by_name(tool_name)
                if tool_instance:
                    logger.info(f"Found tool {tool_name} in tool registry, executing directly")
                    tool = tool_instance.get_tool()
                    try:
                        if hasattr(tool, 'invoke'):
                            result = tool.invoke(tool_args)
                        else:
                            result = tool(tool_args)
                        
                        results.append(ToolResult(
                            tool=tool_name,
                            args=tool_args,
                            output=result,
                            error="",
                            tool_call_id=tool_call_id  # Propagate tool_call_id to result
                        ))
                        output_preview = str(result)[:100] if result else "(empty)"
                        logger.info(f"[TOOL_EXECUTION] Tool {tool_name} executed successfully via registry: output_length={len(str(result)) if result else 0}, output_preview={output_preview}...")
                    except Exception as e:
                        logger.error(f"Error executing tool {tool_name} from registry: {e}", exc_info=True)
                        results.append(ToolResult(
                            tool=tool_name,
                            args=tool_args,
                            output=None,
                            error=str(e),
                            tool_call_id=tool_call_id  # Propagate tool_call_id to result even on error
                        ))
                else:
                    logger.error(f"Tool {tool_name} not found in tool registry either")
                    results.append(ToolResult(
                        tool=tool_name,
                        args=tool_args,
                        output=None,
                        error=f"Tool {tool_name} is not available",
                        tool_call_id=tool_call_id  # Propagate tool_call_id to result
                    ))
            except Exception as e:
                logger.error(f"Error accessing tool registry: {e}", exc_info=True)
                # Final fallback: Try direct import for known tools
                if tool_name == "get_current_time":
                    try:
                        logger.info(f"Attempting direct import of {tool_name} tool")
                        from app.agents.tools.time_tool import TimeTool
                        time_tool = TimeTool()
                        tool = time_tool.get_tool()
                        result = tool.invoke(tool_args) if hasattr(tool, 'invoke') else tool(tool_args)
                        results.append(ToolResult(
                            tool=tool_name,
                            args=tool_args,
                            output=result,
                            error="",
                            tool_call_id=tool_call_id  # Propagate tool_call_id to result
                        ))
                        logger.info(f"[TOOL_EXECUTION] Tool {tool_name} executed successfully via direct import: output_preview={str(result)[:100]}...")
                    except Exception as import_error:
                        logger.error(f"Error with direct import of {tool_name}: {import_error}", exc_info=True)
                        results.append(ToolResult(
                            tool=tool_name,
                            args=tool_args,
                            output=None,
                            error=f"Tool {tool_name} is not available: {str(import_error)}",
                            tool_call_id=tool_call_id  # Propagate tool_call_id to result even on error
                        ))
                else:
                    results.append(ToolResult(
                        tool=tool_name,
                        args=tool_args,
                        output=None,
                        error=f"Tool {tool_name} is not available: {str(e)}",
                        tool_call_id=tool_call_id  # Propagate tool_call_id to result
                    ))
    
    logger.info(f"[TOOL_EXECUTION] Completed execution: {len(results)} results returned")
    return results


@task
def agent_with_tool_results_task(
    agent_name: str,
    query: str,
    messages: List[BaseMessage],
    tool_results: List[ToolResult],
    user_id: Optional[int],
    model_name: Optional[str] = None,
    config: Optional[RunnableConfig] = None
) -> AgentResponse:
    """
    Unified task for processing tool results with agent.
    
    Handles both:
    - Postprocess: Single tool executed, format output
    - Refine: Multiple tools executed, agent decides next steps
    
    Args:
        agent_name: Name of agent to use
        query: Original user query
        messages: Conversation history (should include tool results as ToolMessages)
        tool_results: List of tool execution results
        user_id: User ID
        model_name: Optional model name
        config: Optional runtime config (for callbacks)
        
    Returns:
        AgentResponse with formatted answer
    """
    try:
        logger.info(f"[AGENT_WITH_TOOL_RESULTS] Starting for agent={agent_name}, query_preview={query[:50] if query else '(empty)'}..., messages_count={len(messages)}, tool_results_count={len(tool_results) if tool_results else 0}")
        
        # Use generic agent task (no hardcoded routing)
        # Note: config is automatically injected by LangGraph, don't pass it explicitly
        result = generic_agent_task(agent_name, query, messages, user_id, model_name).result()
        
        logger.info(f"[AGENT_WITH_TOOL_RESULTS] Agent task returned: has_reply={bool(result.reply)}, reply_preview={result.reply[:50] if result.reply else '(empty)'}..., tool_calls_count={len(result.tool_calls) if result.tool_calls else 0}")
        return result
    except Exception as e:
        logger.error(f"Error in agent_with_tool_results_task: {e}", exc_info=True)
        return AgentResponse(
            type="answer",
            reply=f"I apologize, but I encountered an error processing tool results: {str(e)}",
            agent_name=agent_name
        )


@task
def check_summarization_needed_task(
    messages: List[BaseMessage],
    token_threshold: int = 40000,
    model_name: Optional[str] = None
) -> bool:
    """
    Check if summarization is needed based on message token count.
    
    Args:
        messages: List of conversation messages
        token_threshold: Token threshold to trigger summarization (default: 4000)
        model_name: Optional model name for token counting
        
    Returns:
        True if summarization is needed, False otherwise
    """
    try:
        # Calculate total token count for all messages
        total_tokens = 0
        for message in messages:
            if hasattr(message, 'content') and message.content:
                content = str(message.content)
                # Count tokens for this message
                tokens = count_tokens(content, model_name)
                total_tokens += tokens
        
        logger.debug(f"Total message tokens: {total_tokens}, threshold: {token_threshold}")
        
        # Check if threshold is exceeded
        needs_summarization = total_tokens >= token_threshold
        
        if needs_summarization:
            logger.info(f"Summarization needed: {total_tokens} tokens >= {token_threshold} threshold")
        else:
            logger.debug(f"Summarization not needed: {total_tokens} tokens < {token_threshold} threshold")
        
        return needs_summarization
    except Exception as e:
        logger.error(f"Error checking summarization need: {e}", exc_info=True)
        # On error, default to not needing summarization
        return False


@task
def save_message_task(
    response: AgentResponse,
    session_id: int,
    user_id: int,
    tool_calls: Optional[List[Dict[str, Any]]] = None,
    run_id: Optional[str] = None,
    parent_message_id: Optional[int] = None
) -> bool:
    """
    Save agent response message to database.
    
    Args:
        response: AgentResponse to save
        session_id: Chat session ID
        user_id: User ID
        tool_calls: Optional tool calls metadata
        
    Returns:
        True if successful
    """
    try:
        session = ChatSession.objects.get(id=session_id)
        
        # Update model_used if not set
        if not session.model_used:
            session.model_used = OPENAI_MODEL
            session.save(update_fields=['model_used'])
        
        # Prepare metadata - persist ALL fields that are displayed in the chat UI
        # Use tool_calls from parameter if provided, otherwise from response
        # The workflow should pass tool_calls with updated statuses
        final_tool_calls = tool_calls if tool_calls is not None else (response.tool_calls or [])
        
        # Ensure all tool_calls have status field for consistency
        # Status can be: 'pending', 'executing', 'completed', 'error'
        # Also truncate large tool outputs
        for tc in final_tool_calls:
            if 'status' not in tc:
                # If tool was executed (has output or result), mark as completed/error
                if tc.get('output') or tc.get('result'):
                    tc['status'] = 'completed'
                elif tc.get('error'):
                    tc['status'] = 'error'
                else:
                    tc['status'] = 'pending'
            
            # Truncate large outputs in tool_calls
            if 'output' in tc and tc['output'] is not None:
                tc['output'] = truncate_tool_output(tc['output'])
            if 'result' in tc and tc['result'] is not None:
                tc['result'] = truncate_tool_output(tc['result'])
        
        # Build comprehensive metadata with ALL display fields
        metadata = {
            "agent_name": response.agent_name or "greeter",  # For agent badge display
            "tool_calls": final_tool_calls,  # Tool calls with statuses
        }
        
        # Add correlation IDs for /run polling (ensures correct message under concurrency)
        if run_id:
            metadata["run_id"] = run_id
        if parent_message_id:
            metadata["parent_message_id"] = parent_message_id
        
        # Add response type and plan data if plan_proposal
        if response.type == "plan_proposal":
            metadata["response_type"] = "plan_proposal"
            if response.plan:
                metadata["plan"] = response.plan
        
        # Add clarification if present
        if response.clarification:
            metadata["clarification"] = response.clarification
        
        # Add raw tool outputs if present (truncate large outputs)
        if response.raw_tool_outputs:
            truncated_outputs = [truncate_tool_output(output) for output in response.raw_tool_outputs]
            metadata["raw_tool_outputs"] = truncated_outputs
        
        # Add token usage to metadata
        if response.token_usage:
            metadata.update({
                "input_tokens": response.token_usage.get("input_tokens", 0),
                "output_tokens": response.token_usage.get("output_tokens", 0),
                "cached_tokens": response.token_usage.get("cached_tokens", 0),
                "model": OPENAI_MODEL,
            })
        
        # Prepare content - use reply or plan description for plan_proposal
        content = response.reply or ""
        if response.type == "plan_proposal" and response.plan:
            # Create a description for plan proposal
            plan_steps = response.plan.get("plan", [])
            content = f"Plan proposal with {len(plan_steps)} step(s) to execute."
        
        # Check if there's an existing message with the same run_id to update instead of creating new one
        # This prevents duplicate messages when tools are approved (initial message with awaiting_approval, then final with completed)
        from app.db.models.message import Message
        existing_message = None
        if run_id:
            try:
                existing_message = Message.objects.filter(
                    session_id=session_id,
                    role="assistant",
                    metadata__run_id=run_id
                ).order_by('-created_at').first()
            except Exception as e:
                logger.warning(f"[MESSAGE_SAVE] Error checking for existing message with run_id={run_id}: {e}")
        
        if existing_message:
            # Update existing message with final tool_calls statuses and content
            existing_message.content = content
            existing_message.tokens_used = response.token_usage.get("total_tokens", 0) if response.token_usage else existing_message.tokens_used
            existing_message.metadata = metadata
            existing_message.save()
            logger.info(f"[MESSAGE_SAVE] Updated existing assistant message ID={existing_message.id} session={session_id} agent={response.agent_name} content_preview={content[:50]}... tokens={response.token_usage.get('total_tokens', 0) if response.token_usage else 0}")
            return True
        else:
            # Save new message
            message = add_message(
                session_id=session_id,
                role="assistant",
                content=content,
                tokens_used=response.token_usage.get("total_tokens", 0) if response.token_usage else 0,
                metadata=metadata
            )
            
            logger.info(f"[MESSAGE_SAVE] Saved new assistant message ID={message.id} session={session_id} agent={response.agent_name} content_preview={content[:50]}... tokens={response.token_usage.get('total_tokens', 0) if response.token_usage else 0}")
            
            return True
    except Exception as e:
        logger.error(f"Error saving message: {e}", exc_info=True)
        return False
