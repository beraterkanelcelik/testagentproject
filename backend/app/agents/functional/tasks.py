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
from app.agents.agents.greeter import GreeterAgent
from app.agents.agents.search import SearchAgent
from app.services.chat_service import get_messages, add_message
from app.db.models.session import ChatSession
from app.agents.config import OPENAI_MODEL
from app.core.logging import get_logger
from app.rag.chunking.tokenizer import count_tokens

logger = get_logger(__name__)

supervisor_agent = SupervisorAgent()
greeter_agent_cache = {}
search_agent_cache = {}


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


@task
def greeter_agent_task(
    query: str,
    messages: List[BaseMessage],
    user_id: Optional[int],
    model_name: Optional[str] = None,
    config: Optional[RunnableConfig] = None
) -> AgentResponse:
    """
    Execute greeter agent and return response.
    
    Args:
        query: User query
        messages: Conversation history
        user_id: User ID for tool access
        model_name: Optional model name
        config: Optional runtime config (for callbacks)
        
    Returns:
        AgentResponse with reply
    """
    try:
        logger.info(f"[GREETER_TASK] Starting greeter_agent_task query_preview={query[:50] if query else '(empty)'}... user_id={user_id} messages_count={len(messages)}")
        
        # Check if summarization is needed
        needs_summarization = check_summarization_needed_task(
            messages=messages,
            token_threshold=40000,
            model_name=model_name
        ).result()
        
        # Get or create greeter agent
        cache_key = f"{user_id}:{model_name or 'default'}"
        if cache_key not in greeter_agent_cache:
            greeter_agent_cache[cache_key] = GreeterAgent(user_id=user_id, model_name=model_name)
        greeter_agent = greeter_agent_cache[cache_key]
        
        # Apply summarization middleware if needed
        if needs_summarization:
            from app.agents.functional.middleware import create_agent_with_summarization
            from langgraph.checkpoint.postgres import PostgresSaver
            from app.settings import DATABASES
            
            # Get checkpointer for middleware
            checkpointer = None
            try:
                db_config = DATABASES['default']
                db_url = (
                    f"postgresql://{db_config['USER']}:{db_config['PASSWORD']}"
                    f"@{db_config['HOST']}:{db_config['PORT']}/{db_config['NAME']}"
                )
                checkpointer_cm = PostgresSaver.from_conn_string(db_url)
                if hasattr(checkpointer_cm, '__enter__'):
                    checkpointer = checkpointer_cm.__enter__()
            except Exception as e:
                logger.warning(f"Failed to get checkpointer for summarization: {e}")
            
            greeter_agent = create_agent_with_summarization(
                agent=greeter_agent,
                model_name=model_name or OPENAI_MODEL,
                checkpointer=checkpointer
            )
            logger.info("Applied SummarizationMiddleware to greeter agent")
        
        # Add user message if not already in messages
        if not messages or not isinstance(messages[-1], HumanMessage) or messages[-1].content != query:
            messages = messages + [HumanMessage(content=query)]
        
        # Invoke agent - LangChain will automatically enable streaming
        # when LangGraph is in streaming mode (stream_mode=["messages"])
        # This allows LangGraph to capture and stream tokens incrementally
        invoke_kwargs = {}
        if config:
            invoke_kwargs['config'] = config
        
        logger.info(f"[GREETER_TASK] Invoking greeter agent with {len(messages)} messages, config_present={bool(config)}")
        response = greeter_agent.invoke(messages, **invoke_kwargs)
        logger.info(f"[GREETER_TASK] Greeter agent response received: type={type(response)}, has_content={hasattr(response, 'content')}, content_length={len(response.content) if hasattr(response, 'content') and response.content else 0}, content_preview={response.content[:50] if hasattr(response, 'content') and response.content else '(empty)'}...")
        
        # Extract token usage
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
        
        # Extract tool calls (preserve full tool_call structure including IDs)
        tool_calls = []
        if hasattr(response, 'tool_calls') and response.tool_calls:
            for tc in response.tool_calls:
                tool_calls.append({
                    "tool": tc.get("name", ""),
                    "name": tc.get("name", ""),
                    "args": tc.get("args", {}),
                    "id": tc.get("id", ""),  # Preserve tool_call ID
                })
        
        # Add the AIMessage to messages list if it has tool_calls
        # This is needed for proper ToolMessage handling
        if hasattr(response, 'tool_calls') and response.tool_calls:
            messages = messages + [response]
        
        reply_content = response.content if hasattr(response, 'content') else str(response)
        logger.info(f"[GREETER_TASK] Creating AgentResponse: reply_length={len(reply_content) if reply_content else 0}, tool_calls_count={len(tool_calls)}")
        
        agent_response = AgentResponse(
            type="answer",
            reply=reply_content,
            tool_calls=tool_calls,
            token_usage=token_usage,
            agent_name=greeter_agent.name  # Use agent's actual name property
        )
        
        logger.info(f"[GREETER_TASK] Returning AgentResponse: has_reply={bool(agent_response.reply)}, reply_preview={agent_response.reply[:50] if agent_response.reply else '(empty)'}...")
        return agent_response
    except Exception as e:
        logger.error(f"[GREETER_TASK] Error in greeter_agent_task: {e}", exc_info=True)
        # Fallback: use "greeter" if agent instance is not available
        return AgentResponse(
            type="answer",
            reply=f"I apologize, but I encountered an error: {str(e)}",
            agent_name="greeter"
        )


@task
def search_agent_task(
    query: str,
    messages: List[BaseMessage],
    user_id: Optional[int],
    model_name: Optional[str] = None,
    config: Optional[RunnableConfig] = None
) -> AgentResponse:
    """
    Execute search agent and return response.
    
    Args:
        query: User query
        messages: Conversation history
        user_id: User ID for tool access
        model_name: Optional model name
        config: Optional runtime config (for callbacks)
        
    Returns:
        AgentResponse with reply
    """
    try:
        # Check if summarization is needed
        needs_summarization = check_summarization_needed_task(
            messages=messages,
            token_threshold=40000,
            model_name=model_name
        ).result()
        
        # Get or create search agent
        cache_key = f"{user_id}:{model_name or 'default'}"
        if cache_key not in search_agent_cache:
            search_agent_cache[cache_key] = SearchAgent(user_id=user_id, model_name=model_name)
        search_agent = search_agent_cache[cache_key]
        
        # Apply summarization middleware if needed
        if needs_summarization:
            from app.agents.functional.middleware import create_agent_with_summarization
            from langgraph.checkpoint.postgres import PostgresSaver
            from app.settings import DATABASES
            
            # Get checkpointer for middleware
            checkpointer = None
            try:
                db_config = DATABASES['default']
                db_url = (
                    f"postgresql://{db_config['USER']}:{db_config['PASSWORD']}"
                    f"@{db_config['HOST']}:{db_config['PORT']}/{db_config['NAME']}"
                )
                checkpointer_cm = PostgresSaver.from_conn_string(db_url)
                if hasattr(checkpointer_cm, '__enter__'):
                    checkpointer = checkpointer_cm.__enter__()
            except Exception as e:
                logger.warning(f"Failed to get checkpointer for summarization: {e}")
            
            search_agent = create_agent_with_summarization(
                agent=search_agent,
                model_name=model_name or OPENAI_MODEL,
                checkpointer=checkpointer
            )
            logger.info("Applied SummarizationMiddleware to search agent")
        
        # Add user message if not already in messages
        if not messages or not isinstance(messages[-1], HumanMessage) or messages[-1].content != query:
            messages = messages + [HumanMessage(content=query)]
        
        # Invoke agent - LangChain will automatically enable streaming
        # when LangGraph is in streaming mode (stream_mode=["messages"])
        # This allows LangGraph to capture and stream tokens incrementally
        invoke_kwargs = {}
        if config:
            invoke_kwargs['config'] = config
        
        logger.info(f"[SEARCH_TASK] Invoking search agent with {len(messages)} messages, config_present={bool(config)}")
        response = search_agent.invoke(messages, **invoke_kwargs)
        logger.info(f"[SEARCH_TASK] Search agent response received: type={type(response)}, has_content={hasattr(response, 'content')}, content_length={len(response.content) if hasattr(response, 'content') and response.content else 0}, has_tool_calls={hasattr(response, 'tool_calls') and bool(response.tool_calls)}, tool_calls_count={len(response.tool_calls) if hasattr(response, 'tool_calls') and response.tool_calls else 0}")
        
        # Extract token usage
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
        
        # Extract tool calls (preserve full tool_call structure including IDs)
        tool_calls = []
        if hasattr(response, 'tool_calls') and response.tool_calls:
            logger.info(f"[SEARCH_TASK] Extracting {len(response.tool_calls)} tool calls from response")
            for tc in response.tool_calls:
                tool_call_dict = {
                    "tool": tc.get("name", ""),
                    "name": tc.get("name", ""),
                    "args": tc.get("args", {}),
                    "id": tc.get("id", ""),  # Preserve tool_call ID
                }
                tool_calls.append(tool_call_dict)
                logger.info(f"[SEARCH_TASK] Extracted tool call: name={tool_call_dict['name']}, args={tool_call_dict['args']}, id={tool_call_dict['id']}")
        else:
            logger.info(f"[SEARCH_TASK] No tool calls in response: has_tool_calls_attr={hasattr(response, 'tool_calls')}, tool_calls_value={getattr(response, 'tool_calls', None)}")
        
        # Add the AIMessage to messages list if it has tool_calls
        # This is needed for proper ToolMessage handling
        if hasattr(response, 'tool_calls') and response.tool_calls:
            messages = messages + [response]
        
        reply_content = response.content if hasattr(response, 'content') else str(response)
        logger.info(f"[SEARCH_TASK] Creating AgentResponse: reply_length={len(reply_content) if reply_content else 0}, tool_calls_count={len(tool_calls)}")
        
        agent_response = AgentResponse(
            type="answer",
            reply=reply_content,
            tool_calls=tool_calls,
            token_usage=token_usage,
            agent_name=search_agent.name  # Use agent's actual name property
        )
        
        logger.info(f"[SEARCH_TASK] Returning AgentResponse: has_reply={bool(agent_response.reply)}, reply_preview={agent_response.reply[:50] if agent_response.reply else '(empty)'}..., tool_calls_count={len(agent_response.tool_calls)}")
        return agent_response
    except Exception as e:
        logger.error(f"Error in search_agent_task: {e}", exc_info=True)
        return AgentResponse(
            type="answer",
            reply=f"I apologize, but I encountered an error: {str(e)}",
            agent_name="search"
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
    Execute a generic agent (routes to specific agent tasks).
    
    Args:
        agent_name: Name of agent to execute
        query: User query
        messages: Conversation history
        user_id: User ID
        tool_results: Optional tool execution results
        model_name: Optional model name
        config: Optional runtime config (for callbacks)
        
    Returns:
        AgentResponse with reply
    """
    # Note: config is automatically injected by LangGraph when calling tasks from within tasks
    if agent_name == "greeter":
        return greeter_agent_task(query, messages, user_id, model_name).result()
    elif agent_name == "search":
        return search_agent_task(query, messages, user_id, model_name).result()
    else:
        # Unknown agent - fallback to greeter
        logger.warning(f"Unknown agent '{agent_name}', falling back to greeter")
        return greeter_agent_task(query, messages, user_id, model_name).result()


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
    
    # Get agent for tools based on agent_name
    # Use same cache key format as agent tasks
    cache_key = f"{user_id}:{model_name or 'default'}"
    agent = None
    
    if agent_name == "greeter":
        if cache_key not in greeter_agent_cache:
            greeter_agent_cache[cache_key] = GreeterAgent(user_id=user_id, model_name=model_name)
        agent = greeter_agent_cache[cache_key]
    elif agent_name == "search":
        if cache_key not in search_agent_cache:
            search_agent_cache[cache_key] = SearchAgent(user_id=user_id, model_name=model_name)
        agent = search_agent_cache[cache_key]
    else:
        # Fallback to greeter
        if cache_key not in greeter_agent_cache:
            greeter_agent_cache[cache_key] = GreeterAgent(user_id=user_id, model_name=model_name)
        agent = greeter_agent_cache[cache_key]
    
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
        tool_name = tool_call.get("name") or tool_call.get("tool")
        tool_args = tool_call.get("args", {})
        
        if not tool_name:
            logger.warning(f"Skipping tool call without name: {tool_call}")
            continue
        
        logger.info(f"Executing tool: {tool_name} with args: {tool_args}")
        
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
                    error=""
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
                    error=str(e)
                ))
            finally:
                # End span
                if span:
                    try:
                        span.end()
                    except Exception:
                        pass
        else:
            logger.warning(f"Tool {tool_name} not found in tool_map")
            results.append(ToolResult(
                tool=tool_name,
                args=tool_args,
                output=None,
                error=f"Tool {tool_name} is not available"
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
        
        # Route to appropriate agent task
        # Note: config is automatically injected by LangGraph, don't pass it explicitly
        if agent_name == "greeter":
            result = greeter_agent_task(query, messages, user_id, model_name).result()
        elif agent_name == "search":
            result = search_agent_task(query, messages, user_id, model_name).result()
        else:
            # Fallback to greeter
            result = greeter_agent_task(query, messages, user_id, model_name).result()
        
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
    tool_calls: Optional[List[Dict[str, Any]]] = None
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
        for tc in final_tool_calls:
            if 'status' not in tc:
                # If tool was executed (has output or error), mark as completed/error
                if tc.get('output') or tc.get('result'):
                    tc['status'] = 'completed'
                elif tc.get('error'):
                    tc['status'] = 'error'
                else:
                    tc['status'] = 'pending'
        
        # Build comprehensive metadata with ALL display fields
        metadata = {
            "agent_name": response.agent_name or "greeter",  # For agent badge display
            "tool_calls": final_tool_calls,  # Tool calls with statuses
        }
        
        # Add response type and plan data if plan_proposal
        if response.type == "plan_proposal":
            metadata["response_type"] = "plan_proposal"
            if response.plan:
                metadata["plan"] = response.plan
        
        # Add clarification if present
        if response.clarification:
            metadata["clarification"] = response.clarification
        
        # Add raw tool outputs if present
        if response.raw_tool_outputs:
            metadata["raw_tool_outputs"] = response.raw_tool_outputs
        
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
        
        # Save message
        message = add_message(
            session_id=session_id,
            role="assistant",
            content=content,
            tokens_used=response.token_usage.get("total_tokens", 0) if response.token_usage else 0,
            metadata=metadata
        )
        
        logger.info(f"[MESSAGE_SAVE] Saved assistant message ID={message.id} session={session_id} agent={response.agent_name} content_preview={content[:50]}... tokens={response.token_usage.get('total_tokens', 0) if response.token_usage else 0}")
        
        return True
    except Exception as e:
        logger.error(f"Error saving message: {e}", exc_info=True)
        return False
