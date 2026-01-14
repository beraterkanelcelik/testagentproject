"""
Main workflow entrypoint for LangGraph Functional API.
"""
import asyncio
from functools import lru_cache
from typing import Optional, List, Dict, Any, AsyncIterator, Union
from langgraph.func import entrypoint
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import interrupt, Command
from langgraph.errors import GraphInterrupt
from app.agents.functional.models import AgentRequest
from langchain_core.messages import HumanMessage, ToolMessage
from app.agents.functional.models import AgentRequest, AgentResponse, ToolProposal
from app.agents.functional.streaming import EventCallbackHandler
from app.agents.functional.tasks import (
    route_to_agent,
    execute_agent,
    refine_with_tool_results,
    execute_tools,
    load_messages_task,
    save_message_task,
)
from app.agents.checkpoint import get_checkpoint_config
from app.core.logging import get_logger

logger = get_logger(__name__)


def build_db_url() -> str:
    """
    Build database connection URL from Django settings.
    
    Returns:
        PostgreSQL connection string
    """
    from app.settings import DATABASES
    
    db_config = DATABASES['default']
    return (
        f"postgresql://{db_config['USER']}:{db_config['PASSWORD']}"
        f"@{db_config['HOST']}:{db_config['PORT']}/{db_config['NAME']}"
    )


@lru_cache(maxsize=1)
def get_sync_checkpointer() -> PostgresSaver:
    """
    Get cached sync checkpointer - connection pool managed by psycopg.

    PostgresSaver.from_conn_string() creates a saver with an internal connection pool.
    We use it as a context manager to properly manage the connection lifecycle.
    @lru_cache ensures we keep the context manager open for the life of the process.

    Returns:
        PostgresSaver instance (context manager kept open by cache)
    """
    try:
        db_url = build_db_url()
        # Create checkpointer - use as context manager but keep it open
        # The context manager manages connection lifecycle
        checkpointer = PostgresSaver.from_conn_string(db_url)

        # Initialize database tables (required by LangGraph)
        # This is safe to call multiple times - it only creates tables if they don't exist
        try:
            checkpointer.setup()
            logger.info("Checkpointer tables initialized successfully")
        except Exception as e:
            # Tables may already exist, or there might be a connection issue
            logger.warning(f"Checkpointer setup warning (tables may already exist): {e}")

        logger.info("Checkpointer created successfully")
        return checkpointer
    except Exception as e:
        logger.error(f"Failed to create checkpointer: {e}", exc_info=True)
        raise


# For async workflows (if needed in the future)
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

_checkpointer_lock = asyncio.Lock()
_async_checkpointer: Optional[AsyncPostgresSaver] = None


async def get_async_checkpointer() -> AsyncPostgresSaver:
    """
    Get or create async checkpointer with proper lifecycle.
    
    Returns:
        AsyncPostgresSaver instance
    """
    global _async_checkpointer
    
    if _async_checkpointer is None:
        async with _checkpointer_lock:
            if _async_checkpointer is None:
                db_url = build_db_url()
                # Create async checkpointer with connection pool
                _async_checkpointer = AsyncPostgresSaver.from_conn_string(db_url)
                await _async_checkpointer.setup()
                logger.info("Async checkpointer created successfully")
    
    return _async_checkpointer


# Backward compatibility alias
def get_checkpointer() -> Optional[PostgresSaver]:
    """
    Get checkpointer instance (backward compatibility).
    
    Returns:
        PostgresSaver instance or None on error
    """
    try:
        return get_sync_checkpointer()
    except Exception as e:
        logger.error(f"Failed to get checkpointer: {e}", exc_info=True)
        return None

# Auto-executable tools per agent
AUTO_EXECUTE_TOOLS = {
    "search": ["rag_retrieval_tool"],
    "greeter": ["rag_retrieval_tool"],
}


def extract_tool_proposals(tool_calls: List[Dict[str, Any]]) -> List[ToolProposal]:
    """
    Extract tool proposals from tool calls.
    
    Args:
        tool_calls: List of tool call dictionaries
        
    Returns:
        List of ToolProposal objects
    """
    proposals = []
    for tc in tool_calls:
        tool_name = tc.get("name") or tc.get("tool")
        tool_args = tc.get("args", {})
        if tool_name:
            proposals.append(ToolProposal(
                tool=tool_name,
                props=tool_args,
                query=""
            ))
    return proposals


# Tools that require human approval before execution
TOOLS_REQUIRING_APPROVAL = {
    "get_current_time",  # Time tool requires approval
}


def tool_requires_approval(tool_name: str) -> bool:
    """
    Check if a tool requires human approval (no side effects).
    
    This is a simple check function used before calling interrupt().
    Following LangGraph best practices for interrupt-based HITL.
    
    Args:
        tool_name: Name of the tool
        
    Returns:
        True if tool requires approval, False otherwise
    """
    # Check TOOLS_REQUIRING_APPROVAL set (most reliable)
    if tool_name in TOOLS_REQUIRING_APPROVAL:
        return True
    
    # Fallback: Check tool registry if tool is registered
    try:
        from app.agents.tools.registry import tool_registry
        tool_instance = tool_registry.get_tool_by_name(tool_name)
        if tool_instance:
            return getattr(tool_instance, 'requires_approval', False)
    except Exception:
        pass
    
    return False


def request_tool_approvals(tool_calls: List[Dict[str, Any]], session_id: int) -> Dict[str, Any]:
    """
    Request approval for tools requiring human-in-the-loop.
    
    Uses LangGraph's native interrupt() pattern. Collects all tools requiring
    approval and calls interrupt() ONCE per turn with the list.
    
    IMPORTANT: Do NOT wrap interrupt() in broad try/except. LangGraph uses
    a special exception for control flow that must propagate.
    
    Args:
        tool_calls: List of tool call dictionaries
        session_id: Chat session ID for logging
        
    Returns:
        Approval decisions dict from resume:
        {
            "approvals": {
                "tool_call_id": {
                    "approved": bool,
                    "args": dict  # Optional edited args
                }
            }
        }
    """
    # Collect tools requiring approval
    to_review = []
    for tc in tool_calls:
        tool_name = tc.get("name") or tc.get("tool", "")
        if tool_requires_approval(tool_name):
            to_review.append({
                "tool_call_id": tc.get("id"),
                "tool": tool_name,
                "args": tc.get("args", {}),
            })
    
    if not to_review:
        return {"approvals": {}}
    
    logger.info(f"[HITL] [INTERRUPT] Requesting approval for {len(to_review)} tools: {[t['tool'] for t in to_review]} session={session_id}")
    
    # Call interrupt() - this pauses execution and waits for resume
    # The interrupt payload will be surfaced to the caller via __interrupt__ in stream
    # When resumed with Command(resume=...), interrupt() returns the resume payload
    decision = interrupt({
        "type": "tool_approval",
        "session_id": session_id,
        "tools": to_review,
    })
    
    # decision is whatever UI returns on resume (the resume payload)
    # Expected shape: {"approvals": {"tool_call_id": {"approved": bool, "args": {...}}}}
    logger.info(f"[HITL] [RESUME] Interrupt returned with approval decisions: {len(decision.get('approvals', {}))} approvals session={session_id}")
    return decision or {"approvals": {}}


def is_auto_executable(tool_name: str, agent_name: str) -> bool:
    """
    Check if a tool is auto-executable for the given agent.
    
    Tools that require approval (human-in-the-loop) are not auto-executable.
    
    Args:
        tool_name: Name of the tool
        agent_name: Name of the agent
        
    Returns:
        True if tool is auto-executable, False if it requires approval
    """
    # Check if tool requires approval
    if tool_name in TOOLS_REQUIRING_APPROVAL:
        return False
    
    # Check auto-execute list
    auto_tools = AUTO_EXECUTE_TOOLS.get(agent_name, [])
    return tool_name in auto_tools


@entrypoint(checkpointer=get_sync_checkpointer())
def ai_agent_workflow(request: Union[AgentRequest, Command, Any]) -> AgentResponse:
    """
    Main entrypoint for AI agent workflow using Functional API.
    
    Handles both regular execution and plan execution.
    
    NOTE: Human-in-the-Loop Implementation:
    Uses LangGraph's native interrupt() pattern for human-in-the-loop tool approval.
    When tools require approval, the workflow calls interrupt() which pauses execution
    within LangGraph. The interrupt payload is surfaced via __interrupt__ in the stream.
    Temporal coordinates by detecting the interrupt event, waiting for a resume signal,
    and re-running the activity with Command(resume=resume_payload) to continue execution.
    
    Reference: https://docs.langchain.com/oss/python/langgraph/interrupts
    - LangGraph's Functional API: Agent orchestration and tool execution
    - LangGraph interrupt(): Pauses execution when tools require approval
    - Temporal: Coordinates workflow durability and resume coordination
    - Redis: Real-time streaming to frontend
    
    When tools require approval, interrupt() is called with tool proposals.
    The interrupt payload is surfaced via __interrupt__ in the stream.
    Temporal workflow waits for resume signal, then re-runs with Command(resume=...).
    LangGraph restores checkpointed state and interrupt() returns approval decisions.
    
    Reference: https://docs.langchain.com/oss/python/langgraph/interrupts
               https://docs.langchain.com/oss/python/langgraph/functional-api#resuming
    
    Args:
        request: AgentRequest with query, session_id, user_id, etc.
                 If plan_steps is provided, executes plan instead of routing.
                 When resuming from interrupt, LangGraph handles Command(resume=...) internally.
        
    Returns:
        AgentResponse with reply, tool_calls, token_usage, etc.
    """
    from langfuse import get_client
    from app.agents.config import LANGFUSE_ENABLED
    
    # Create span for workflow if Langfuse is enabled
    # Use trace_id from request if available (created in activity)
    # Note: We use start_observation() here (not start_as_current_observation) because
    # the workflow runs in a separate thread context. The CallbackHandler will use
    # the OpenTelemetry context set via propagate_attributes() in the thread.
    langfuse = None
    trace_span = None
    # Handle trace_id for both AgentRequest and Command
    trace_id_for_langfuse = getattr(request, 'trace_id', None) if not isinstance(request, Command) else None
    if LANGFUSE_ENABLED and trace_id_for_langfuse:
        try:
            langfuse = get_client()
            if langfuse:
                # Create span within the trace hierarchy using trace_context
                # This creates the span but doesn't make it "current" in this context
                # The propagate_attributes() in the thread will ensure CallbackHandler uses the trace
                flow = getattr(request, 'flow', 'main') if not isinstance(request, Command) else 'main'
                plan_steps = getattr(request, 'plan_steps', None) if not isinstance(request, Command) else None
                user_id = getattr(request, 'user_id', None) if not isinstance(request, Command) else None
                session_id = getattr(request, 'session_id', None) if not isinstance(request, Command) else None
                trace_span = langfuse.start_observation(
                    as_type="span",
                    trace_context={"trace_id": trace_id_for_langfuse},
                    name="ai_agent_workflow",
                    metadata={
                        "flow": flow,
                        "has_plan_steps": bool(plan_steps),
                        "user_id": str(user_id) if user_id else None,
                        "session_id": str(session_id) if session_id else None,
                    }
                )
                logger.debug(f"[LANGFUSE] Created workflow span for trace_id={trace_id_for_langfuse}")
        except Exception as e:
            logger.warning(f"Failed to create Langfuse span for workflow: {e}", exc_info=True)
    
    try:
        # Handle Command(resume=...) vs AgentRequest
        # IMPORTANT: On resume, the node restarts from the beginning (LangGraph behavior)
        # So we must follow the same path for both initial and resume
        # The key difference: on resume, we check for pending tool_calls in messages
        # and skip re-invoking the agent if they exist
        
        # Get checkpointer instance first (needed for both paths)
        checkpointer = get_checkpointer()
        
        # Extract session_id - from request or from resume payload
        if isinstance(request, Command):
            # Resume: get session_id from enveloped resume payload
            if hasattr(request, 'resume') and isinstance(request.resume, dict):
                current_session_id = request.resume.get("session_id")
            else:
                logger.error("[HITL] [RESUME] Command resume missing session_id in resume payload")
                return AgentResponse(
                    type="answer",
                    reply="Error: Resume requires session context",
                    agent_name="system"
                )
            current_user_id = None  # Can't get from Command, but may not be needed for resume
            current_run_id = None  # Command resume: correlation IDs not available (not needed for resume)
            current_parent_message_id = None
            logger.info(f"[HITL] [RESUME] Command resume - session_id={current_session_id}")
        else:
            # Initial run: get from AgentRequest
            current_session_id = request.session_id
            current_user_id = request.user_id
            current_run_id = getattr(request, 'run_id', None)  # Correlation ID for /run polling
            current_parent_message_id = getattr(request, 'parent_message_id', None)  # Parent message ID for correlation
        
        # CRITICAL: Always use the same thread_id format for both initial and resume
        # This ensures LangGraph uses the same checkpoint
        thread_id = f"chat_session_{current_session_id}" if current_session_id else f"user_{current_user_id}" if current_user_id else "default"
        checkpoint_config = get_checkpoint_config(current_session_id) if current_session_id else {"configurable": {"thread_id": thread_id}}
        
        # Regular workflow execution - SAME PATH for both initial and resume
        # On resume, the node restarts from top, so we need to:
        # 1. Load messages
        # 2. Check if there's a pending approval state (last assistant message with tool_calls)
        # 3. If pending, use those tool_calls; otherwise invoke agent normally
        
        # Check if this is plan execution (only for AgentRequest)
        if not isinstance(request, Command) and request.plan_steps:
            return _execute_plan_workflow(request, checkpoint_config, checkpointer, thread_id)
        
        # Load messages from checkpoint or database (ALWAYS, even on resume)
        messages = load_messages_task(
            session_id=current_session_id,
            checkpointer=checkpointer,
            thread_id=thread_id
        ).result()
        
        # Check if we're resuming from interrupt (Command resume)
        # Look for the last assistant message with tool_calls in "awaiting_approval" state
        pending_tool_calls = None
        if isinstance(request, Command):
            # On resume, check if last message has pending tool_calls
            from langchain_core.messages import AIMessage
            for msg in reversed(messages):
                if isinstance(msg, AIMessage) and hasattr(msg, 'tool_calls') and msg.tool_calls:
                    # Check if tool_calls have "status" indicating they're awaiting approval
                    # We stored them before interrupt with status="pending" or similar
                    tool_calls_data = msg.tool_calls
                    if isinstance(tool_calls_data, list) and tool_calls_data:
                        # Check if any tool_call requires approval and hasn't been executed
                        approval_required_tools = [
                            tc for tc in tool_calls_data
                            if tool_requires_approval(tc.get("name") or tc.get("tool", ""))
                            and tc.get("status") in (None, "pending", "awaiting_approval")
                        ]
                        if approval_required_tools:
                            pending_tool_calls = tool_calls_data
                            logger.info(f"[HITL] [RESUME] Found pending tool_calls in last assistant message: {len(approval_required_tools)} tools awaiting approval")
                            break
        
        # If not resuming with pending tool_calls, proceed with normal flow
        if not isinstance(request, Command) or pending_tool_calls is None:
            # Initial run or resume without pending tool_calls - proceed normally
            if not isinstance(request, Command):
                # Add user message if not already present (only on initial run)
                if not messages or not isinstance(messages[-1], HumanMessage) or messages[-1].content != request.query:
                    messages = messages + [HumanMessage(content=request.query)]
            
            # Supervisor routing (skip on resume if we have pending tool_calls)
            if pending_tool_calls is None:
                # Need routing for initial run or resume without pending tool_calls
                if isinstance(request, Command):
                    # On resume, we need the query - get from last human message
                    last_human_msg = next((msg for msg in reversed(messages) if isinstance(msg, HumanMessage)), None)
                    query = last_human_msg.content if last_human_msg else ""
                else:
                    query = request.query
                
                routing = route_to_agent(
                    messages=messages,
                    config=checkpoint_config
                ).result()
                
                logger.info(f"Supervisor routed to agent: {routing.agent}")
                
                # Check for clarification request
                if routing.require_clarification:
                    return AgentResponse(
                        type="answer",
                        reply=routing.query,
                        clarification=routing.query,
                        agent_name="supervisor"
                    )
                
                # Normal flow: invoke agent
                # When resuming from interrupt, LangGraph will restore checkpointed state
                # and interrupt() will return the resume payload (approval decisions)
                # Use generic agent task (no hardcoded routing)
                logger.info(f"[WORKFLOW] Routing to {routing.agent} agent for query_preview={routing.query[:50] if routing.query else '(empty)'}...")
                response = execute_agent(
                    agent_name=routing.agent,
                    messages=messages,
                    user_id=current_user_id,
                    model_name=None,
                    config=checkpoint_config
                ).result()
                logger.info(f"[WORKFLOW] {routing.agent} agent returned: has_reply={bool(response.reply)}, reply_preview={response.reply[:50] if response.reply else '(empty)'}..., tool_calls_count={len(response.tool_calls) if response.tool_calls else 0}")
            else:
                # Resume with pending tool_calls - reconstruct response from stored tool_calls
                # Get routing agent from last assistant message or response metadata
                routing_agent = "greeter"  # Default
                if messages:
                    last_ai_msg = next((msg for msg in reversed(messages) if isinstance(msg, AIMessage)), None)
                    if last_ai_msg:
                        # Try to get agent from response_metadata
                        if hasattr(last_ai_msg, 'response_metadata'):
                            routing_agent = last_ai_msg.response_metadata.get("agent", "greeter")
                        # Also check if we can get from message content or tool_calls metadata
                
                # Reconstruct AgentResponse from pending tool_calls
                # These tool_calls already have IDs and status="awaiting_approval"
                response = AgentResponse(
                    type="answer",
                    reply="",  # No reply yet, waiting for tool execution
                    tool_calls=pending_tool_calls,
                    agent_name=routing_agent
                )
                logger.info(f"[HITL] [RESUME] Reconstructed response from pending tool_calls: {len(pending_tool_calls)} tools, agent={routing_agent}")
                # Skip adding AIMessage again - it's already in messages from load_messages_task
        
        # Track executed tool_calls to preserve them in final response (for streaming)
        executed_tool_calls_with_status = None
        
        # Handle tool calls with proposal flow
        # On resume, if we have pending_tool_calls, response was reconstructed from them
        # On initial run, response comes from agent invocation above
        if response and response.tool_calls:
            logger.info(f"Found {len(response.tool_calls)} tool calls")
            
            # Build tool_calls with proper IDs
            # IMPORTANT: Always generate unique IDs - never reuse based on signature
            # IDs should only be stable if persisted from stored tool_calls
            import uuid
            from langchain_core.messages import AIMessage
            
            for tc in response.tool_calls:
                tool_call_id = tc.get("id")
                if not tool_call_id:
                    # Always generate a new unique ID when missing
                    tool_call_id = f"call_{uuid.uuid4().hex[:16]}"
                    tc['id'] = tool_call_id  # Store ID back in tool_call
            
            # Partition tools into 3 buckets BEFORE creating AIMessage
            # This allows us to apply approvals and then create AIMessage with final args
            # 1. auto_tools: safe to auto-execute
            # 2. approval_tools: require human approval (interrupt)
            # 3. manual_tools: not auto-exec, but also not approval-required (execute immediately)
            
            # Get routing agent for tool partitioning
            # On resume with pending_tool_calls, routing might not be defined
            # Use response.agent_name as fallback
            if 'routing' in locals() and routing:
                routing_agent = routing.agent
            else:
                # Fallback to agent_name from response
                routing_agent = response.agent_name if hasattr(response, 'agent_name') and response.agent_name else "greeter"
            
            # Use helper function to partition tools
            partitioned = partition_tools(response.tool_calls, routing_agent)
            auto_tools = partitioned["auto"]
            approval_tools = partitioned["approval"]
            manual_tools = partitioned["manual"]
            
            logger.info(f"[WORKFLOW] Tool partitioning: auto={len(auto_tools)} approval={len(approval_tools)} manual={len(manual_tools)} session={current_session_id}")
            
            # IMPORTANT: Store tool_calls before interrupt ONLY on initial run (not resume)
            # Mark approval-required tools with status="awaiting_approval" so we can find them on resume
            if not isinstance(request, Command) and current_session_id:
                for tc in response.tool_calls:
                    tool_name = tc.get("name") or tc.get("tool", "")
                    if tool_requires_approval(tool_name):
                        # Mark as awaiting approval before interrupt
                        tc["status"] = "awaiting_approval"
                
                # Store assistant message with tool_calls before interrupt
                # This allows us to retrieve them on resume without re-invoking the agent
                if any(tool_requires_approval(tc.get("name") or tc.get("tool", "")) for tc in response.tool_calls):
                    try:
                        save_message_task(
                            response=AgentResponse(
                                type="answer",
                                reply=response.reply or "",
                                tool_calls=response.tool_calls,  # Include status="awaiting_approval"
                                agent_name=response.agent_name
                            ),
                            session_id=current_session_id,
                            user_id=current_user_id,
                            tool_calls=response.tool_calls,
                            run_id=current_run_id,
                            parent_message_id=current_parent_message_id
                        ).result()
                        logger.info(f"[HITL] [STORE] Stored assistant message with {len([tc for tc in response.tool_calls if tool_requires_approval(tc.get('name') or tc.get('tool', ''))])} tools awaiting approval session={current_session_id}")
                    except Exception as e:
                        logger.warning(f"[HITL] [STORE] Failed to store assistant message before interrupt: {e}")
            
            # Request approval for tools requiring human-in-the-loop (LangGraph native interrupt pattern)
            # This calls interrupt() ONCE per turn with all tools requiring approval
            # After resume, interrupt() returns the approval decisions
            approvals = {}
            if approval_tools:
                logger.info(f"[HITL] [INTERRUPT] Requesting approval for {len(approval_tools)} tools requiring approval session={current_session_id}")
                approval_decisions = request_tool_approvals(approval_tools, current_session_id or 0)
                approvals = approval_decisions.get("approvals", {})
                
                # Apply approvals to approval tools
                for tc in approval_tools:
                    tool_call_id = tc.get("id")
                    tool_name = tc.get("name") or tc.get("tool", "")
                    
                    approval = approvals.get(tool_call_id, {"approved": False})
                    if approval.get("approved"):
                        # Tool was approved - allow edited args if provided
                        if "args" in approval:
                            tc["args"] = approval["args"]
                        tc["status"] = "approved"
                        logger.info(f"[HITL] Tool approved: tool={tool_name} tool_call_id={tool_call_id} session={current_session_id}")
                    else:
                        # Tool was rejected
                        tc["status"] = "rejected"
                        logger.info(f"[HITL] Tool rejected: tool={tool_name} tool_call_id={tool_call_id} session={current_session_id}")
            
            # IMPORTANT: Create AIMessage AFTER approvals are applied
            # This ensures tool_calls have final args (including any edits from approval)
            # This is required before adding ToolMessages (OpenAI API requirement)
            tool_calls_with_ids = []
            for tc in response.tool_calls:
                tool_calls_with_ids.append({
                    "name": tc.get("name") or tc.get("tool", ""),
                    "args": tc.get("args", {}),
                    "id": tc.get("id")
                })
            
            ai_message_with_tool_calls = AIMessage(
                content=response.reply or "",
                tool_calls=tool_calls_with_ids
            )
            messages = messages + [ai_message_with_tool_calls]
            
            # Collect tools to execute: auto + manual + approved(approval)
            tools_to_execute = auto_tools + manual_tools + [tc for tc in approval_tools if tc.get("status") == "approved"]
            
            # Execute all tools that should run
            all_tool_results = []
            if tools_to_execute:
                logger.info(f"[WORKFLOW] Executing {len(tools_to_execute)} tools: auto={len(auto_tools)} manual={len(manual_tools)} approved={len([tc for tc in approval_tools if tc.get('status') == 'approved'])} session={current_session_id}")
                # Include tool_call_id in tool_calls_to_execute for deterministic mapping
                tool_calls_to_execute = [
                    {
                        "id": tc.get("id"),  # Include tool_call_id
                        "name": tc.get("name") or tc.get("tool"),
                        "args": tc.get("args", {})
                    }
                    for tc in tools_to_execute
                ]
                
                # Get routing agent for tool execution
                if 'routing' in locals() and routing:
                    tool_exec_agent = routing.agent
                else:
                    # Fallback to agent_name from response
                    tool_exec_agent = response.agent_name if hasattr(response, 'agent_name') and response.agent_name else "greeter"
                
                tool_results = execute_tools(
                    tool_calls=tool_calls_to_execute,
                    agent_name=tool_exec_agent,
                    user_id=current_user_id,
                    config=checkpoint_config
                ).result()
                all_tool_results.extend(tool_results)
                logger.info(f"[WORKFLOW] Tool execution completed: {len(tool_results)} results")
            
            # Update tool_calls with execution status
            # Mark executed tools as completed or error
            # IMPORTANT: Match by tool_call_id for deterministic mapping (not by tool name/args)
            tool_results = all_tool_results
            for tc in tools_to_execute:
                tool_call_id = tc.get("id")
                # Find matching tool result by tool_call_id
                matching_result = next(
                    (tr for tr in tool_results if tr.tool_call_id == tool_call_id),
                    None
                )
                if matching_result:
                    if matching_result.error:
                        tc["status"] = "error"
                        tc["error"] = matching_result.error
                    else:
                        tc["status"] = "completed"
                        tc["output"] = matching_result.output
                else:
                    # Tool was supposed to be executed but no result (error case)
                    tc["status"] = "error"
                    tc["error"] = f"Tool execution failed - no result returned for tool_call_id={tool_call_id}"
            
            # Update database: Mark approved tools as completed after execution
            # This ensures the first message (saved before interrupt) reflects completed status
            if approval_tools and current_run_id:
                try:
                    from app.db.models.message import Message
                    existing_message = Message.objects.filter(
                        session_id=current_session_id,
                        role="assistant",
                        metadata__run_id=current_run_id
                    ).order_by('created_at').first()
                    
                    if existing_message:
                        # Update tool_calls in the existing message with completed statuses
                        existing_metadata = existing_message.metadata or {}
                        existing_tool_calls = existing_metadata.get("tool_calls", [])
                        
                        # Update tool call statuses to match the executed tools
                        updated_tool_calls = []
                        for existing_tc in existing_tool_calls:
                            tool_call_id = existing_tc.get("id")
                            # Find matching executed tool
                            matching_executed = next(
                                (tc for tc in tools_to_execute if tc.get("id") == tool_call_id),
                                None
                            )
                            if matching_executed:
                                # Use the status from executed tool (completed/error)
                                updated_tool_calls.append(matching_executed)
                            else:
                                # Keep original if not found (shouldn't happen)
                                updated_tool_calls.append(existing_tc)
                        
                        # Update message metadata with completed tool_calls
                        existing_metadata["tool_calls"] = updated_tool_calls
                        existing_message.metadata = existing_metadata
                        existing_message.save()
                        logger.info(f"[HITL] [DB_UPDATE] Updated message ID={existing_message.id} with completed tool statuses session={current_session_id}")
                except Exception as e:
                    logger.warning(f"[HITL] [DB_UPDATE] Failed to update message with completed tool statuses: {e} session={current_session_id}", exc_info=True)
            
            # Only process tool results and call agent_with_tool_results_task if we have tool results
            # If we have pending tools but no tool results, skip this step to avoid OpenAI API errors
            if tool_results:
                # Add tool results as ToolMessages
                # IMPORTANT: Use tool_call_id directly from ToolResult for deterministic mapping
                # This eliminates ambiguity from matching by (tool_name, args)
                tool_messages = []
                
                for tr in tool_results:
                    # Use tool_call_id from ToolResult (propagated from tool execution)
                    # Fallback to generated ID only if missing (shouldn't happen with proper flow)
                    tool_call_id = tr.tool_call_id
                    if not tool_call_id:
                        # Fallback: try to find matching tool_call_id from AIMessage
                        for tc in ai_message_with_tool_calls.tool_calls:
                            if (tc.get("name") or tc.get("tool", "")) == tr.tool:
                                tool_call_id = tc.get("id")
                                if tool_call_id:
                                    break
                    
                    if not tool_call_id:
                        # Last resort: generate unique ID (shouldn't happen in normal flow)
                        import uuid
                        tool_call_id = f"{tr.tool}_{uuid.uuid4().hex[:8]}"
                        logger.warning(f"[WORKFLOW] ToolResult missing tool_call_id, generated fallback: {tool_call_id} tool={tr.tool}")
                    
                    tool_msg = ToolMessage(
                        content=str(tr.output) if tr.output is not None else str(tr.error) if tr.error else "",
                        tool_call_id=tool_call_id,
                        name=tr.tool
                    )
                    tool_messages.append(tool_msg)
                
                # Add tool messages to conversation
                messages = messages + tool_messages
                
                # PRESERVE tool_calls with statuses before refine step
                # The refined response might not include these, but we need to save them
                executed_tool_calls_with_status = response.tool_calls.copy() if response.tool_calls else []
                
                # Re-invoke agent with tool results (refine)
                # Get routing agent and query
                if 'routing' in locals() and routing:
                    refine_agent = routing.agent
                    refine_query = routing.query
                else:
                    # Fallback to agent_name from response and query from last human message
                    refine_agent = response.agent_name if hasattr(response, 'agent_name') and response.agent_name else "greeter"
                    last_human_msg = next((msg for msg in reversed(messages) if isinstance(msg, HumanMessage)), None)
                    refine_query = last_human_msg.content if last_human_msg else ""
                logger.info(f"[WORKFLOW] Invoking agent_with_tool_results_task for agent={refine_agent} with {len(tool_results)} tool results, messages_count={len(messages)}")
                refined_response = refine_with_tool_results(
                    agent_name=refine_agent,
                    messages=messages,
                    tool_results=tool_results,
                    user_id=current_user_id,
                    model_name=None,
                    config=checkpoint_config
                ).result()
                logger.info(f"[WORKFLOW] agent_with_tool_results_task returned: has_reply={bool(refined_response.reply)}, reply_preview={refined_response.reply[:50] if refined_response.reply else '(empty)'}..., tool_calls_count={len(refined_response.tool_calls) if refined_response.tool_calls else 0}")
                
                # Preserve tool_calls from original response (with statuses) in refined response
                # This ensures tool_calls with execution statuses are saved
                if executed_tool_calls_with_status:
                    refined_response.tool_calls = executed_tool_calls_with_status
                
                # Use refined response as the final response
                response = refined_response
            
            # Check if there are rejected tools that should create a plan proposal
            rejected_tools = [tc for tc in approval_tools if tc.get("status") == "rejected"]
            if rejected_tools and not tool_results:
                # If we have rejected tools and no tool results, create plan proposal
                logger.info(f"[HITL] Creating plan proposal for {len(rejected_tools)} rejected tools session={current_session_id}")
                # Get routing agent and query
                if 'routing' in locals() and routing:
                    plan_routing_agent = routing.agent
                    plan_query = routing.query
                else:
                    # Fallback to agent_name from response and query from last human message
                    plan_routing_agent = response.agent_name if hasattr(response, 'agent_name') and response.agent_name else "greeter"
                    last_human_msg = next((msg for msg in reversed(messages) if isinstance(msg, HumanMessage)), None)
                    plan_query = last_human_msg.content if last_human_msg else ""
                plan_steps = [
                    {
                        "action": "tool",
                        "tool": tc.get("name") or tc.get("tool"),
                        "props": tc.get("args", {}),
                        "agent": plan_routing_agent,
                        "query": plan_query,
                    }
                    for tc in rejected_tools
                ]
                return AgentResponse(
                    type="plan_proposal",
                    plan={
                        "type": "plan_proposal",
                        "plan": plan_steps,
                        "plan_index": 0,
                        "plan_total": len(plan_steps),
                    },
                    agent_name=plan_routing_agent,
                    tool_calls=rejected_tools
                )
        
        # Save message to database if session_id provided
        # Save both regular answers and plan proposals
        # IMPORTANT: Preserve tool_calls from initial response (before refine) if they were executed
        # The refined response might not have tool_calls, but we want to save the executed ones
        final_tool_calls = response.tool_calls
        
        # Ensure tool_calls are in the final response for streaming
        # If we executed tools earlier, they should be preserved in the response
        # But if they're missing (e.g., after refine), restore them from executed_tool_calls_with_status
        if not response.tool_calls and executed_tool_calls_with_status:
            response.tool_calls = executed_tool_calls_with_status
            final_tool_calls = executed_tool_calls_with_status
            logger.info(f"Restored {len(final_tool_calls)} tool_calls in final response for streaming")
        
        if current_session_id and (response.reply or response.type == "plan_proposal"):
            # If we had tool calls earlier and they were executed, preserve them
            # Check if we're in a tool execution flow (response might be from refine step)
            # In that case, tool_calls should already be in response from the initial agent call
            # But if we executed tools, we need to preserve those tool_calls with their statuses
            save_message_task(
                response=response,
                session_id=current_session_id,
                user_id=current_user_id,
                tool_calls=final_tool_calls,  # Pass tool_calls with updated statuses
                run_id=current_run_id,
                parent_message_id=current_parent_message_id
            ).result()
        
        # Calculate context usage for frontend display
        try:
            from app.agents.context_usage import calculate_context_usage
            # Get model name from session or use default
            model_name = None
            if current_session_id:
                try:
                    from app.db.models.session import ChatSession
                    session = ChatSession.objects.get(id=current_session_id)
                    if session.model_used:
                        model_name = session.model_used
                except Exception:
                    pass
            # Calculate and add context usage to response
            context_usage = calculate_context_usage(messages, model_name)
            response.context_usage = context_usage
        except Exception as e:
            logger.warning(f"Failed to calculate context usage: {e}", exc_info=True)
        
        # Update trace with final response
        if trace_span:
            try:
                trace_span.update(
                    output={
                        "type": response.type,
                        "agent_name": response.agent_name,
                        "has_reply": bool(response.reply),
                        "tool_calls_count": len(response.tool_calls) if response.tool_calls else 0,
                    }
                )
            except Exception as e:
                logger.warning(f"Failed to update Langfuse trace: {e}")
            finally:
                # Ensure span is ended
                try:
                    if trace_span:
                        trace_span.end()
                except Exception:
                    pass
        
        return response
        
    except GraphInterrupt:
        # GraphInterrupt is a control flow exception - don't catch it
        # Let it propagate to LangGraph's stream() handler
        raise
    except Exception as e:
        logger.error(f"Error in ai_agent_workflow: {e}", exc_info=True)
        
        # Update trace with error
        if trace_span:
            try:
                trace_span.update(
                    output=None,
                    level="ERROR",
                    status_message=str(e)
                )
            except Exception:
                pass
            finally:
                # Ensure span is ended
                try:
                    if trace_span:
                        trace_span.end()
                except Exception:
                    pass
        
        return AgentResponse(
            type="answer",
            reply=f"I apologize, but I encountered an error: {str(e)}",
            agent_name="system"
        )


def extract_response_from_chunk(chunk: Any) -> Optional[AgentResponse]:
    """
    Extract AgentResponse from LangGraph stream chunk.
    Handles multiple chunk formats returned by Functional API.
    
    Args:
        chunk: Stream chunk from LangGraph (can be dict, AgentResponse, etc.)
        
    Returns:
        AgentResponse if extracted successfully, None otherwise
    """
    if isinstance(chunk, AgentResponse):
        return chunk
    
    if isinstance(chunk, dict):
        # Check for 'ai_agent_workflow' key
        if 'ai_agent_workflow' in chunk:
            response_data = chunk['ai_agent_workflow']
            logger.debug(f"[STREAM_CHUNK] Found 'ai_agent_workflow' key, response_data type={type(response_data)}")
            if isinstance(response_data, AgentResponse):
                logger.info(f"[STREAM_CHUNK] Extracted AgentResponse from 'ai_agent_workflow' key: agent={response_data.agent_name}, has_reply={bool(response_data.reply)}")
                return response_data
            elif isinstance(response_data, dict):
                # Try to construct AgentResponse from dict
                try:
                    response = AgentResponse(**response_data)
                    logger.info(f"[STREAM_CHUNK] Constructed AgentResponse from dict: agent={response.agent_name}, has_reply={bool(response.reply)}")
                    return response
                except Exception as e:
                    logger.warning(f"[STREAM_CHUNK] Failed to construct AgentResponse from dict: {e}")
        
        # Check if chunk itself is response dict
        elif any(key in chunk for key in ['agent_name', 'reply', 'tool_calls', 'type']):
            try:
                response = AgentResponse(**chunk)
                logger.info(f"[STREAM_CHUNK] Constructed AgentResponse from chunk dict: agent={response.agent_name}, has_reply={bool(response.reply)}")
                return response
            except Exception as e:
                logger.warning(f"[STREAM_CHUNK] Failed to construct AgentResponse from chunk: {e}, chunk_keys={list(chunk.keys())}")
    
    return None


def extract_interrupt_value(interrupt_raw: Any) -> Dict[str, Any]:
    """
    Extract interrupt value from LangGraph Interrupt object.
    Handles multiple formats: tuple, Interrupt object, dict, list.
    
    Args:
        interrupt_raw: Raw interrupt object from LangGraph (various formats)
        
    Returns:
        Dict with interrupt data (tool_approval info, etc.)
    """
    # Handle tuple format (most common from LangGraph)
    if isinstance(interrupt_raw, tuple) and len(interrupt_raw) > 0:
        interrupt_obj = interrupt_raw[0]
        if hasattr(interrupt_obj, 'value'):
            return interrupt_obj.value
        elif isinstance(interrupt_obj, dict) and 'value' in interrupt_obj:
            return interrupt_obj['value']
    
    # Handle direct Interrupt object
    if hasattr(interrupt_raw, 'value'):
        return interrupt_raw.value
    
    # Handle dict format
    if isinstance(interrupt_raw, dict):
        if 'value' in interrupt_raw:
            return interrupt_raw['value']
        elif interrupt_raw.get('type') == 'tool_approval':
            return interrupt_raw
    
    # Handle list format (serialized tuple)
    if isinstance(interrupt_raw, list) and len(interrupt_raw) > 0:
        first_item = interrupt_raw[0]
        if isinstance(first_item, dict):
            if 'value' in first_item:
                return first_item['value']
            elif first_item.get('type') == 'tool_approval':
                return first_item
    
    # Fallback: return raw data if we couldn't extract value
    logger.warning(f"[HITL] [INTERRUPT] Could not extract interrupt value, using raw data: {type(interrupt_raw)}")
    return interrupt_raw if isinstance(interrupt_raw, dict) else {}


def partition_tools(
    tool_calls: List[Dict[str, Any]], 
    agent_name: str
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Partition tools into auto-executable, approval-required, and manual buckets.
    
    Args:
        tool_calls: List of tool call dictionaries
        agent_name: Name of the agent (for auto-executable check)
        
    Returns:
        Dict with keys: 'auto', 'approval', 'manual' containing partitioned tool calls
    """
    auto_tools = []
    approval_tools = []
    manual_tools = []
    
    for tc in tool_calls:
        tool_name = tc.get("name") or tc.get("tool", "")
        if is_auto_executable(tool_name, agent_name):
            auto_tools.append(tc)
        elif tool_requires_approval(tool_name):
            approval_tools.append(tc)
        else:
            manual_tools.append(tc)
    
    return {
        "auto": auto_tools,
        "approval": approval_tools,
        "manual": manual_tools
    }


def _execute_plan_workflow(
    request: AgentRequest,
    checkpoint_config: Dict[str, Any],
    checkpointer: Optional[PostgresSaver],
    thread_id: str
) -> AgentResponse:
    """
    Execute plan workflow (internal helper function).
    
    Args:
        request: AgentRequest with plan_steps
        checkpoint_config: Checkpoint configuration
        checkpointer: Checkpointer instance
        thread_id: Thread ID for checkpoint
        
    Returns:
        AgentResponse with combined results
    """
    from langfuse import get_client
    from app.agents.config import LANGFUSE_ENABLED
    
    # Create span for plan execution if Langfuse is enabled
    # Use trace_id from request if available (created in activity)
    langfuse = None
    plan_span = None
    if LANGFUSE_ENABLED and request.trace_id:
        try:
            langfuse = get_client()
            if langfuse:
                # Create span within the trace hierarchy using trace_context
                plan_span = langfuse.start_observation(
                    as_type="span",
                    trace_context={"trace_id": request.trace_id},
                    name="plan_execution",
                    metadata={
                        "plan_steps_count": len(request.plan_steps) if request.plan_steps else 0,
                        "user_id": str(request.user_id) if request.user_id else None,
                        "session_id": str(request.session_id) if request.session_id else None,
                    }
                )
                logger.debug(f"[LANGFUSE] Created plan execution span for trace_id={request.trace_id}")
        except Exception as e:
            logger.warning(f"Failed to create Langfuse span for plan execution: {e}", exc_info=True)
    
    try:
        
        # Load messages
        messages = load_messages_task(
            session_id=request.session_id,
            checkpointer=checkpointer,
            thread_id=thread_id
        ).result()
        
        results: List[str] = []
        raw_tool_outputs: List[Dict[str, Any]] = []
        
        # Process each plan step
        for step in request.plan_steps or []:
            action = step.get("action")
            
            if action == "answer":
                answer = step.get("answer", "")
                if answer:
                    results.append(answer)
                continue
            
            if action == "tool":
                tool_name = step.get("tool")
                tool_args = step.get("props", {})
                agent_name = step.get("agent", "greeter")
                step_query = step.get("query", request.query)
                
                # Execute tool
                tool_calls = [{"name": tool_name, "args": tool_args}]
                tool_results = execute_tools(
                    tool_calls=tool_calls,
                    user_id=request.user_id,
                    agent_name=agent_name,
                    config=checkpoint_config
                ).result()
                
                if tool_results:
                    tool_result = tool_results[0]
                    
                    # Import truncate function
                    from app.agents.functional.tasks import truncate_tool_output
                    
                    # Store raw output (truncate large outputs)
                    raw_tool_outputs.append({
                        "tool": tool_result.tool,
                        "args": tool_result.args,
                        "output": truncate_tool_output(tool_result.output),
                    })
                    
                    # Add tool result as ToolMessage
                    # Generate proper tool_call_id (consistent with main workflow UUID-based approach)
                    import uuid
                    tool_call_id = tool_result.tool_call_id
                    if not tool_call_id:
                        # Generate UUID-based ID (consistent with main workflow pattern)
                        tool_call_id = f"call_{uuid.uuid4().hex[:16]}"
                    
                    tool_msg = ToolMessage(
                        content=str(tool_result.output) if tool_result.output else tool_result.error,
                        tool_call_id=tool_call_id,
                        name=tool_result.tool
                    )
                    messages = messages + [tool_msg]
                    
                    # Post-process with agent
                    if tool_result.output is not None or tool_result.error:
                        agent_response = refine_with_tool_results(
                            agent_name=agent_name,
                            messages=messages,
                            tool_results=tool_results,
                            user_id=request.user_id,
                            model_name=None,
                            config=checkpoint_config
                        ).result()
                        
                        if agent_response.reply:
                            results.append(agent_response.reply)
        
        # Combine results
        final_text = "\n".join(results) if results else ""
        
        # Save message if session_id provided
        if request.session_id and final_text:
            final_response = AgentResponse(
                type="answer",
                reply=final_text,
                agent_name=request.plan_steps[0].get("agent", "greeter") if request.plan_steps else "greeter"
            )
            save_message_task(
                response=final_response,
                session_id=request.session_id,
                user_id=request.user_id,
                tool_calls=[],
                run_id=getattr(request, 'run_id', None),
                parent_message_id=getattr(request, 'parent_message_id', None)
            ).result()
        
        # Update plan execution trace
        if plan_span:
            try:
                plan_span.update(
                    output={
                        "steps_completed": len(results),
                        "tools_executed": len(raw_tool_outputs) if raw_tool_outputs else 0,
                        "final_text_length": len(final_text),
                    }
                )
                plan_span.end()
            except Exception as e:
                logger.warning(f"Failed to update Langfuse plan execution trace: {e}")
        
        return AgentResponse(
            type="answer",
            reply=final_text,
            raw_tool_outputs=raw_tool_outputs if raw_tool_outputs else None,
            agent_name=request.plan_steps[0].get("agent", "greeter") if request.plan_steps else "greeter"
        )
    except Exception as e:
        logger.error(f"Error in plan execution: {e}", exc_info=True)
        
        # Update plan execution trace with error
        if plan_span:
            try:
                plan_span.update(
                    output=None,
                    level="ERROR",
                    status_message=str(e)
                )
            except Exception:
                pass
            finally:
                # Ensure span is ended
                try:
                    if plan_span:
                        plan_span.end()
                except Exception:
                    pass
        
        return AgentResponse(
            type="answer",
            reply=f"I apologize, but I encountered an error executing the plan: {str(e)}",
            agent_name="system"
        )


async def ai_agent_workflow_events(request: Union[AgentRequest, Command], session_id: Optional[int] = None, user_id: Optional[int] = None, trace_id: Optional[str] = None) -> AsyncIterator[Dict[str, Any]]:
    """
    Event-emitting wrapper around ai_agent_workflow.
    Yields structured events during workflow execution.
    
    Args:
        request: AgentRequest with query, session_id, user_id, etc.
                 Or Command(resume=...) when resuming from interrupt.
        session_id: Optional session_id (required when request is Command)
        user_id: Optional user_id (required when request is Command)
        trace_id: Optional trace_id (required when request is Command)
        
    Yields:
        Event dictionaries with type and data
    """
    from threading import Thread
    from queue import Queue as ThreadQueue, Empty
    
    # Extract session_id, user_id, trace_id - handle both AgentRequest and Command
    if isinstance(request, AgentRequest):
        session_id = session_id or request.session_id
        user_id = user_id or request.user_id
        trace_id = trace_id or request.trace_id
    # If Command, use provided session_id/user_id/trace_id (should be passed from runner)
    
    # Status messages mapping
    # Note: Task names match @task function names for EventCallbackHandler
    status_messages = {
        "supervisor_task": "Routing to agent...",
        "load_messages_task": "Loading conversation history...",
        "check_summarization_needed_task": "Checking if summarization needed...",
        "generic_agent_task": "Processing with agent...",
        "agent_task": "Processing with agent...",
        "tool_execution_task": "Executing tools...",
        "agent_with_tool_results_task": "Processing tool results...",
        "save_message_task": "Saving message...",
    }
    
    # Create thread-safe queue for events from callbacks
    # Bound queue to prevent unbounded memory growth
    MAX_QUEUE_SIZE = 10000  # ~10MB assuming 1KB per event
    event_queue = ThreadQueue(maxsize=MAX_QUEUE_SIZE)
    
    # Create event callback handler for streaming
    callback_handler = EventCallbackHandler(event_queue, status_messages)
    
    # Get checkpoint config
    thread_id = f"chat_session_{session_id}" if session_id else f"user_{user_id}" if user_id else "default"
    checkpoint_config = get_checkpoint_config(session_id) if session_id else {"configurable": {"thread_id": thread_id}}
    
    # Add callbacks to config
    if 'callbacks' not in checkpoint_config:
        checkpoint_config['callbacks'] = []
    checkpoint_config['callbacks'].append(callback_handler)
    
    # Add Langfuse CallbackHandler if enabled and trace_id is available
    # This captures LLM calls and associates them with the trace
    from app.agents.config import LANGFUSE_ENABLED
    if LANGFUSE_ENABLED and trace_id:
        try:
            from app.observability.tracing import get_callback_handler
            langfuse_callback = get_callback_handler()
            if langfuse_callback:
                checkpoint_config['callbacks'].append(langfuse_callback)
                logger.debug(f"[LANGFUSE] Added CallbackHandler to workflow for trace_id={trace_id}")
        except Exception as e:
            logger.warning(f"Failed to add Langfuse CallbackHandler: {e}", exc_info=True)
    
    # Track final response and interrupt - use list for thread-safe sharing
    final_response_holder = [None]
    interrupt_holder = [None]
    exception_holder = [None]
    
    # Run workflow in a thread (since stream() is sync)
    def run_workflow():
        try:
            # Use propagate_attributes to set trace context for Langfuse CallbackHandler
            # This ensures all LLM calls are associated with the trace
            from app.agents.config import LANGFUSE_ENABLED
            from langfuse import propagate_attributes
            from app.observability.tracing import prepare_trace_context
            
            if LANGFUSE_ENABLED and trace_id:
                # Create active workflow span using start_as_current_observation
                # This makes it the active observation in OpenTelemetry context
                # The CallbackHandler will automatically use this as the parent trace
                from langfuse import get_client
                langfuse = get_client()
                if langfuse:
                    # Prepare trace context for propagate_attributes
                    trace_context = prepare_trace_context(
                        user_id=user_id or 0,
                        session_id=session_id,
                        metadata={"trace_id": trace_id}  # Store trace_id in metadata for reference
                    )
                    
                    # Extract flow and plan_steps if request is AgentRequest
                    flow = getattr(request, 'flow', 'main') if isinstance(request, AgentRequest) else 'main'
                    plan_steps = getattr(request, 'plan_steps', None) if isinstance(request, AgentRequest) else None
                    
                    # Create active workflow span with trace_context - this makes it the active observation
                    with langfuse.start_as_current_observation(
                        as_type="span",
                        trace_context={"trace_id": trace_id},
                        name="ai_agent_workflow",
                        metadata={
                            "flow": flow,
                            "has_plan_steps": bool(plan_steps),
                            "user_id": str(user_id) if user_id else None,
                            "session_id": str(session_id) if session_id else None,
                        }
                    ) as workflow_span:
                        # Use propagate_attributes to propagate user_id, session_id, metadata to all child observations
                        with propagate_attributes(**trace_context):
                            # Use stream() to get state updates
                            # LangGraph Functional API stream() returns state dictionaries
                            # The final chunk should contain the AgentResponse
                            # Also detect __interrupt__ chunks for human-in-the-loop
                            chunk_count = 0
                            for chunk in ai_agent_workflow.stream(request, config=checkpoint_config):
                                chunk_count += 1
                                logger.debug(f"[STREAM_CHUNK] Received chunk #{chunk_count}, type={type(chunk)}, keys={list(chunk.keys()) if isinstance(chunk, dict) else 'N/A'}")
                                
                                # Check for interrupt (LangGraph native interrupt pattern)
                                if isinstance(chunk, dict) and "__interrupt__" in chunk:
                                    interrupt_holder[0] = chunk["__interrupt__"]
                                    logger.info(f"[HITL] [INTERRUPT] Detected __interrupt__ in stream chunk session={session_id}")
                                    break
                                
                                # Extract response from chunk using helper function
                                extracted_response = extract_response_from_chunk(chunk)
                                if extracted_response:
                                    final_response_holder[0] = extracted_response
                            
                            if final_response_holder[0]:
                                logger.info(f"[STREAM_CHUNK] Final response extracted successfully: agent={final_response_holder[0].agent_name}, type={final_response_holder[0].type}, has_reply={bool(final_response_holder[0].reply)}")
                            else:
                                logger.warning(f"[STREAM_CHUNK] No final response extracted after {chunk_count} chunks")
                            
                            # Update workflow span with final response
                            if final_response_holder[0]:
                                try:
                                    workflow_span.update(
                                        output={
                                            "type": final_response_holder[0].type,
                                            "agent_name": final_response_holder[0].agent_name,
                                            "has_reply": bool(final_response_holder[0].reply),
                                        }
                                    )
                                except Exception as e:
                                    logger.debug(f"Failed to update workflow span: {e}")
                            
                            # Check for interrupt after Langfuse branch completes
                            if interrupt_holder[0]:
                                logger.info(f"[HITL] [INTERRUPT] Interrupt detected in Langfuse branch session={session_id}")
                                return
            else:
                # No Langfuse tracing - run without context managers
                chunk_count = 0
                for chunk in ai_agent_workflow.stream(request, config=checkpoint_config):
                    chunk_count += 1
                    logger.debug(f"[STREAM_CHUNK] Received chunk #{chunk_count}, type={type(chunk)}, keys={list(chunk.keys()) if isinstance(chunk, dict) else 'N/A'}")
                    
                    # Check for interrupt (LangGraph native interrupt pattern)
                    if isinstance(chunk, dict) and "__interrupt__" in chunk:
                        interrupt_holder[0] = chunk["__interrupt__"]
                        logger.info(f"[HITL] [INTERRUPT] Detected __interrupt__ in stream chunk session={session_id}")
                        break
                    
                    # Extract response from chunk using helper function
                    extracted_response = extract_response_from_chunk(chunk)
                    if extracted_response:
                        final_response_holder[0] = extracted_response
                
                if final_response_holder[0]:
                    logger.info(f"[STREAM_CHUNK] Final response extracted successfully: agent={final_response_holder[0].agent_name}, type={final_response_holder[0].type}, has_reply={bool(final_response_holder[0].reply)}")
                else:
                    logger.warning(f"[STREAM_CHUNK] No final response extracted after {chunk_count} chunks")
        except Exception as e:
            logger.error(f"Error in workflow execution: {e}", exc_info=True)
            exception_holder[0] = e
    
    # Start workflow in background thread
    workflow_thread = Thread(target=run_workflow, daemon=True)
    workflow_thread.start()
    logger.info(f"[EVENT_QUEUE] Started workflow thread, waiting for events (queue_size={event_queue.qsize()})")
    
    # Yield events from queue while workflow runs
    workflow_done = False
    timeout_count = 0
    max_timeout = 600  # 10 minutes total
    events_yielded = 0
    
    while not workflow_done and timeout_count < max_timeout:
        try:
            # Poll thread-safe queue (non-blocking)
            try:
                event = event_queue.get_nowait()
                timeout_count = 0  # Reset timeout on event
                event_type = event.get("type", "unknown")
                events_yielded += 1
                # Only log non-token events to reduce verbosity
                if event_type != "token":
                    logger.debug(f"[EVENT_QUEUE] Consumed event #{events_yielded} type={event_type} (queue_size={event_queue.qsize()})")
                yield event
                
                # Check for final event
                if event_type == "final":
                    workflow_done = True
                    logger.info(f"[EVENT_QUEUE] Received final event, stopping queue consumption")
                    break
            except Empty:
                timeout_count += 1
                # Check if workflow thread is still alive
                if not workflow_thread.is_alive():
                    logger.debug(f"[EVENT_QUEUE] Workflow thread finished, checking for remaining events (queue_size={event_queue.qsize()})")
                    workflow_done = True
                    # Try to drain remaining events from queue
                    try:
                        while True:
                            event = event_queue.get_nowait()
                            event_type = event.get("type", "unknown")
                            logger.debug(f"[EVENT_QUEUE] Draining event type={event_type} after thread completion")
                            yield event
                            if event_type == "final":
                                break
                    except Empty:
                        pass
                    break
                # Sleep briefly to avoid busy-waiting
                await asyncio.sleep(0.1)
                continue
                
        except Exception as e:
            logger.error(f"[EVENT_QUEUE] Error reading from event queue: {e}", exc_info=True)
            break
    
    # Wait for workflow thread to complete
    workflow_thread.join(timeout=5.0)
    
    # Check for exceptions
    if exception_holder[0]:
        yield {
            "type": "error",
            "error": str(exception_holder[0])
        }
        return
    
    # Check for interrupt first (takes precedence over final response)
    if interrupt_holder[0]:
        logger.info(f"[HITL] [INTERRUPT] Yielding interrupt event session={session_id}")
        
        # Extract interrupt value using helper function
        interrupt_data = extract_interrupt_value(interrupt_holder[0])
        
        yield {
            "type": "interrupt",
            "data": interrupt_data
        }
        return
    
    # Yield final response if we have it (get from thread-safe holder)
    final_response = final_response_holder[0]
    if final_response:
        # Extract tool_calls and agent_name for update event
        if final_response.tool_calls or final_response.agent_name:
            update_data = {}
            if final_response.agent_name:
                update_data["agent_name"] = final_response.agent_name
            if final_response.tool_calls:
                formatted_tool_calls = []
                for tc in final_response.tool_calls:
                    formatted_tc = {
                        "name": tc.get("name") or tc.get("tool", ""),
                        "tool": tc.get("name") or tc.get("tool", ""),
                        "args": tc.get("args", {}),
                        "status": tc.get("status", "completed"),
                    }
                    if tc.get("id"):
                        formatted_tc["id"] = tc.get("id")
                    if tc.get("output"):
                        formatted_tc["output"] = tc.get("output")
                    if tc.get("error"):
                        formatted_tc["error"] = tc.get("error")
                    formatted_tool_calls.append(formatted_tc)
                
                update_data["tool_calls"] = formatted_tool_calls
            
            if update_data:
                yield {
                    "type": "update",
                    "data": update_data
                }
        
        # Yield final response (interrupt events are handled above in stream loop)
        yield {
            "type": "final",
            "response": final_response
        }
    else:
        # No final response extracted - this should not happen if extraction works correctly
        # Log error instead of invoking workflow again (which causes double execution)
        logger.error(f"[STREAM_ERROR] No final response extracted from stream chunks. This indicates a bug in extraction logic.")
        yield {
            "type": "error",
            "error": "Failed to extract final response from workflow stream. Check logs for details."
        }
