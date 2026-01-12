"""
Main workflow entrypoint for LangGraph Functional API.
"""
import asyncio
from typing import Optional, List, Dict, Any, AsyncIterator
from langgraph.func import entrypoint
from langgraph.checkpoint.postgres import PostgresSaver
from langchain_core.messages import HumanMessage, ToolMessage
from app.agents.functional.models import AgentRequest, AgentResponse, ToolProposal
from app.agents.functional.streaming import EventCallbackHandler
from app.agents.functional.tasks import (
    supervisor_task,
    load_messages_task,
    check_summarization_needed_task,
    greeter_agent_task,
    search_agent_task,
    agent_task,
    tool_execution_task,
    agent_with_tool_results_task,
    save_message_task,
)
from app.agents.checkpoint import get_checkpoint_config
from app.core.logging import get_logger

logger = get_logger(__name__)


# Global checkpointer instance and context manager
_checkpointer = None
_checkpointer_cm = None


class CheckpointerWrapper:
    """
    Wrapper for PostgresSaver that handles connection timeouts.
    Recreates the checkpointer if connection is closed.
    """
    def __init__(self):
        self._checkpointer = None
        self._checkpointer_cm = None
        self._recreate_checkpointer()
    
    def _recreate_checkpointer(self):
        """Create a new checkpointer instance."""
        try:
            from app.settings import DATABASES
            from langgraph.checkpoint.postgres import PostgresSaver
            
            db_config = DATABASES['default']
            db_url = (
                f"postgresql://{db_config['USER']}:{db_config['PASSWORD']}"
                f"@{db_config['HOST']}:{db_config['PORT']}/{db_config['NAME']}"
            )
            
            # PostgresSaver.from_conn_string() returns a context manager
            # Enter it to get the actual checkpointer instance
            self._checkpointer_cm = PostgresSaver.from_conn_string(db_url)
            self._checkpointer = self._checkpointer_cm.__enter__()
            
            # Setup tables if needed
            try:
                self._checkpointer.setup()
            except Exception:
                pass  # Tables may already exist
            
            logger.info("Checkpointer created successfully")
        except Exception as e:
            logger.error(f"Failed to create checkpointer: {e}", exc_info=True)
            self._checkpointer = None
            self._checkpointer_cm = None
    
    def _get_checkpointer(self):
        """Get checkpointer, recreating if connection is closed."""
        if self._checkpointer is None:
            self._recreate_checkpointer()
        return self._checkpointer
    
    def __getattr__(self, name):
        """Delegate all attribute access to the underlying checkpointer."""
        checkpointer = self._get_checkpointer()
        if checkpointer is None:
            raise RuntimeError("Checkpointer is not available")
        
        try:
            attr = getattr(checkpointer, name)
        except AttributeError:
            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")
        
        # Wrap methods to handle connection errors
        if callable(attr):
            def wrapper(*args, **kwargs):
                # Get the method from the current checkpointer
                current_checkpointer = self._get_checkpointer()
                if current_checkpointer is None:
                    raise RuntimeError("Checkpointer is not available")
                
                method = getattr(current_checkpointer, name)
                
                try:
                    return method(*args, **kwargs)
                except Exception as e:
                    error_str = str(e).lower()
                    # Check for connection-related errors
                    if any(phrase in error_str for phrase in ['connection is closed', 'connection closed', 'the connection is closed']):
                        logger.warning(f"Connection closed, recreating checkpointer: {e}")
                        # Close old context manager if it exists
                        if self._checkpointer_cm and hasattr(self._checkpointer_cm, '__exit__'):
                            try:
                                self._checkpointer_cm.__exit__(None, None, None)
                            except Exception:
                                pass
                        self._recreate_checkpointer()
                        # Retry once with new checkpointer
                        current_checkpointer = self._get_checkpointer()
                        if current_checkpointer:
                            method = getattr(current_checkpointer, name)
                            return method(*args, **kwargs)
                    raise
            return wrapper
        return attr


def get_checkpointer() -> Optional[PostgresSaver]:
    """
    Get checkpointer instance (wrapper that handles connection timeouts).
    """
    global _checkpointer
    if _checkpointer is None:
        _checkpointer = CheckpointerWrapper()
    return _checkpointer


# Create checkpointer instance for @entrypoint
# Note: @entrypoint requires an actual checkpointer instance, not a context manager
# We use a wrapper that automatically recreates the connection if it's closed
_checkpointer_instance = get_checkpointer()

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


def is_auto_executable(tool_name: str, agent_name: str) -> bool:
    """
    Check if a tool is auto-executable for the given agent.
    
    Args:
        tool_name: Name of the tool
        agent_name: Name of the agent
        
    Returns:
        True if tool is auto-executable
    """
    auto_tools = AUTO_EXECUTE_TOOLS.get(agent_name, [])
    return tool_name in auto_tools


@entrypoint(checkpointer=_checkpointer_instance)
def ai_agent_workflow(request: AgentRequest) -> AgentResponse:
    """
    Main entrypoint for AI agent workflow using Functional API.
    
    Handles both regular execution and plan execution.
    
    Args:
        request: AgentRequest with query, session_id, user_id, etc.
                 If plan_steps is provided, executes plan instead of routing.
        
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
    if LANGFUSE_ENABLED and request.trace_id:
        try:
            langfuse = get_client()
            if langfuse:
                # Create span within the trace hierarchy using trace_context
                # This creates the span but doesn't make it "current" in this context
                # The propagate_attributes() in the thread will ensure CallbackHandler uses the trace
                trace_span = langfuse.start_observation(
                    as_type="span",
                    trace_context={"trace_id": request.trace_id},
                    name="ai_agent_workflow",
                    metadata={
                        "flow": request.flow,
                        "has_plan_steps": bool(request.plan_steps),
                        "user_id": str(request.user_id) if request.user_id else None,
                        "session_id": str(request.session_id) if request.session_id else None,
                    }
                )
                logger.debug(f"[LANGFUSE] Created workflow span for trace_id={request.trace_id}")
        except Exception as e:
            logger.warning(f"Failed to create Langfuse span for workflow: {e}", exc_info=True)
    
    try:
        # Get thread ID for checkpoint
        thread_id = f"chat_session_{request.session_id}" if request.session_id else f"user_{request.user_id}"
        checkpoint_config = get_checkpoint_config(request.session_id) if request.session_id else {"configurable": {"thread_id": thread_id}}
        
        # Get checkpointer instance (wrapper handles connection management)
        checkpointer = get_checkpointer()
        
        # Check if this is plan execution
        if request.plan_steps:
            return _execute_plan_workflow(request, checkpoint_config, checkpointer, thread_id)
        
        # Regular workflow execution
        # Load messages from checkpoint or database
        messages = load_messages_task(
            session_id=request.session_id,
            checkpointer=checkpointer,
            thread_id=thread_id
        ).result()
        
        # Add user message if not already present
        if not messages or not isinstance(messages[-1], HumanMessage) or messages[-1].content != request.query:
            messages = messages + [HumanMessage(content=request.query)]
        
        # Supervisor routing
        routing = supervisor_task(
            query=request.query,
            messages=messages,
            config=checkpoint_config
        ).result()
        
        logger.info(f"Supervisor routed to agent: {routing.agent}")
        
        # Track executed tool_calls to preserve them in final response (for streaming)
        executed_tool_calls_with_status = None
        
        # Check for clarification request
        if routing.require_clarification:
            return AgentResponse(
                type="answer",
                reply=routing.query,
                clarification=routing.query,
                agent_name="supervisor"
            )
        
        # Route to appropriate agent
        if routing.agent == "greeter":
            logger.info(f"[WORKFLOW] Routing to greeter agent for query_preview={routing.query[:50] if routing.query else '(empty)'}...")
            response = greeter_agent_task(
                query=routing.query,
                messages=messages,
                user_id=request.user_id,
                model_name=None,
                config=checkpoint_config
            ).result()
            logger.info(f"[WORKFLOW] Greeter agent returned: has_reply={bool(response.reply)}, reply_preview={response.reply[:50] if response.reply else '(empty)'}...")
        elif routing.agent == "search":
            logger.info(f"[WORKFLOW] Routing to search agent for query_preview={routing.query[:50] if routing.query else '(empty)'}...")
            response = search_agent_task(
                query=routing.query,
                messages=messages,
                user_id=request.user_id,
                model_name=None,
                config=checkpoint_config
            ).result()
            logger.info(f"[WORKFLOW] Search agent returned: has_reply={bool(response.reply)}, reply_preview={response.reply[:50] if response.reply else '(empty)'}..., tool_calls_count={len(response.tool_calls) if response.tool_calls else 0}")
        else:
            response = agent_task(
                agent_name=routing.agent,
                query=routing.query,
                messages=messages,
                user_id=request.user_id,
                tool_results=None,
                model_name=None,
                config=checkpoint_config
            ).result()
        
        # Handle tool calls with proposal flow
        if response.tool_calls:
            logger.info(f"Found {len(response.tool_calls)} tool calls")
            
            # Initialize tool call statuses as 'pending' if not already set
            for tc in response.tool_calls:
                if 'status' not in tc:
                    tc['status'] = 'pending'
            
            # Create AIMessage with tool_calls from the response
            # This is required before adding ToolMessages (OpenAI API requirement)
            from langchain_core.messages import AIMessage
            
            # Build tool_calls with proper IDs
            # IMPORTANT: Ensure each tool call has a unique ID, even if same tool is called multiple times
            import uuid
            tool_calls_with_ids = []
            seen_tool_call_signatures = {}  # Track (tool_name, args_hash) -> tool_call_id to reuse IDs for same calls
            
            for tc in response.tool_calls:
                tool_call_id = tc.get("id")
                tool_name = tc.get("name") or tc.get("tool", "")
                tool_args = tc.get("args", {})
                
                if not tool_call_id:
                    # Create signature for this tool call
                    args_str = str(sorted(tool_args.items())) if isinstance(tool_args, dict) else str(tool_args)
                    signature = (tool_name, hash(args_str))
                    
                    # Check if we've seen this exact tool call before (same tool + same args)
                    if signature in seen_tool_call_signatures:
                        # Reuse the ID for the same tool call
                        tool_call_id = seen_tool_call_signatures[signature]
                    else:
                        # Generate unique ID for this tool call
                        tool_call_id = f"call_{uuid.uuid4().hex[:16]}"
                        seen_tool_call_signatures[signature] = tool_call_id
                    
                    tc['id'] = tool_call_id  # Store ID back in tool_call
                
                tool_calls_with_ids.append({
                    "name": tool_name,
                    "args": tool_args,
                    "id": tool_call_id
                })
            
            ai_message_with_tool_calls = AIMessage(
                content=response.reply or "",
                tool_calls=tool_calls_with_ids
            )
            messages = messages + [ai_message_with_tool_calls]
            
            # Extract tool proposals
            tool_proposals = extract_tool_proposals(response.tool_calls)
            
            # Separate auto-executable from pending
            auto_executable = [
                p for p in tool_proposals
                if is_auto_executable(p.tool, routing.agent)
            ]
            pending = [
                p for p in tool_proposals
                if not is_auto_executable(p.tool, routing.agent)
            ]
            
            # Auto-execute tools in parallel if any
            if auto_executable:
                logger.info(f"[WORKFLOW] Auto-executing {len(auto_executable)} tools for agent={routing.agent}: {[p.tool for p in auto_executable]}")
                tool_calls_auto = [
                    {"name": p.tool, "args": p.props}
                    for p in auto_executable
                ]
                
                tool_results = tool_execution_task(
                    tool_calls=tool_calls_auto,
                    user_id=request.user_id,
                    agent_name=routing.agent,
                    chat_session_id=request.session_id,
                    config=checkpoint_config
                ).result()
                logger.info(f"[WORKFLOW] Tool execution completed: {len(tool_results)} results, results_preview={[{'tool': tr.tool, 'has_output': bool(tr.output), 'has_error': bool(tr.error)} for tr in tool_results]}")
                
                # Update tool_calls with execution status
                # Mark executed tools as completed or error
                for tc in response.tool_calls:
                    tool_name = tc.get("name") or tc.get("tool", "")
                    # Check if this tool was auto-executed
                    if any(p.tool == tool_name for p in auto_executable):
                        # Find matching tool result
                        matching_result = next(
                            (tr for tr in tool_results if tr.tool == tool_name),
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
                            tc["error"] = "Tool execution failed - no result returned"
                
                # Add tool results as ToolMessages
                # Match tool_call_id with the id from the AIMessage tool_calls
                # IMPORTANT: Match by both tool name AND args to handle multiple calls of same tool
                tool_messages = []
                used_tool_call_ids = set()  # Track used IDs to prevent duplicates
                
                for tr in tool_results:
                    # Find matching tool_call_id from the AIMessage we just created
                    # Match by tool name AND args to handle multiple calls of same tool
                    tool_call_id = None
                    for tc in ai_message_with_tool_calls.tool_calls:
                        tc_name = tc.get("name") or tc.get("tool", "")
                        tc_args = tc.get("args", {})
                        # Match by name and args (compare args as dict)
                        if tc_name == tr.tool and tc_args == tr.args:
                            tool_call_id = tc.get("id")
                            # Ensure this ID hasn't been used yet
                            if tool_call_id and tool_call_id not in used_tool_call_ids:
                                break
                            elif tool_call_id in used_tool_call_ids:
                                # This ID was already used, continue searching
                                tool_call_id = None
                                continue
                    
                    if not tool_call_id:
                        # Fallback: try to get from response.tool_calls
                        for tc in response.tool_calls:
                            tc_name = tc.get("name") or tc.get("tool", "")
                            tc_args = tc.get("args", {})
                            if tc_name == tr.tool and tc_args == tr.args:
                                tool_call_id = tc.get("id")
                                if tool_call_id and tool_call_id not in used_tool_call_ids:
                                    break
                                elif tool_call_id in used_tool_call_ids:
                                    tool_call_id = None
                                    continue
                    
                    if not tool_call_id:
                        # Generate unique ID with index to ensure uniqueness
                        import uuid
                        tool_call_id = f"{tr.tool}_{uuid.uuid4().hex[:8]}"
                    
                    # Mark this ID as used
                    used_tool_call_ids.add(tool_call_id)
                    
                    tool_msg = ToolMessage(
                        content=str(tr.output) if tr.output else tr.error,
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
                logger.info(f"[WORKFLOW] Invoking agent_with_tool_results_task for agent={routing.agent} with {len(tool_results)} tool results, messages_count={len(messages)}")
                refined_response = agent_with_tool_results_task(
                    agent_name=routing.agent,
                    query=routing.query,
                    messages=messages,
                    tool_results=tool_results,
                    user_id=request.user_id,
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
                
                # Check for more tool calls after refine
                if response.tool_calls:
                    # Extract new proposals
                    new_proposals = extract_tool_proposals(response.tool_calls)
                    # Filter out already auto-executed tools
                    pending = [
                        p for p in new_proposals
                        if not is_auto_executable(p.tool, routing.agent)
                    ]
            
            # Create plan proposal if pending tools
            if pending:
                logger.info(f"Creating plan proposal with {len(pending)} pending tools")
                plan_steps = [
                    {
                        "action": "tool",
                        "tool": p.tool,
                        "props": p.props,
                        "agent": routing.agent,
                        "query": routing.query,
                    }
                    for p in pending
                ]
                return AgentResponse(
                    type="plan_proposal",
                    plan={
                        "type": "plan_proposal",
                        "plan": plan_steps,
                        "plan_index": 0,
                        "plan_total": len(plan_steps),
                    },
                    agent_name=routing.agent
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
        
        if request.session_id and (response.reply or response.type == "plan_proposal"):
            # If we had tool calls earlier and they were executed, preserve them
            # Check if we're in a tool execution flow (response might be from refine step)
            # In that case, tool_calls should already be in response from the initial agent call
            # But if we executed tools, we need to preserve those tool_calls with their statuses
            save_message_task(
                response=response,
                session_id=request.session_id,
                user_id=request.user_id,
                tool_calls=final_tool_calls  # Pass tool_calls with updated statuses
            ).result()
        
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
                tool_results = tool_execution_task(
                    tool_calls=tool_calls,
                    user_id=request.user_id,
                    agent_name=agent_name,
                    chat_session_id=request.session_id,
                    config=checkpoint_config
                ).result()
                
                if tool_results:
                    tool_result = tool_results[0]
                    
                    # Store raw output
                    raw_tool_outputs.append({
                        "tool": tool_result.tool,
                        "args": tool_result.args,
                        "output": tool_result.output,
                    })
                    
                    # Add tool result as ToolMessage
                    tool_msg = ToolMessage(
                        content=str(tool_result.output) if tool_result.output else tool_result.error,
                        tool_call_id=f"{tool_result.tool}_{hash(str(tool_result.args))}",
                        name=tool_result.tool
                    )
                    messages = messages + [tool_msg]
                    
                    # Post-process with agent
                    if tool_result.output is not None or tool_result.error:
                        agent_response = agent_with_tool_results_task(
                            agent_name=agent_name,
                            query=step_query,
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
                tool_calls=[]
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


async def ai_agent_workflow_events(request: AgentRequest) -> AsyncIterator[Dict[str, Any]]:
    """
    Event-emitting wrapper around ai_agent_workflow.
    Yields structured events during workflow execution.
    
    Args:
        request: AgentRequest with query, session_id, user_id, etc.
        
    Yields:
        Event dictionaries with type and data
    """
    from threading import Thread
    from queue import Queue as ThreadQueue, Empty
    
    # Status messages mapping
    status_messages = {
        "supervisor_task": "Routing to agent...",
        "load_messages_task": "Loading conversation history...",
        "check_summarization_needed_task": "Checking if summarization needed...",
        "greeter_agent_task": "Processing with greeter agent...",
        "search_agent_task": "Searching documents...",
        "agent_task": "Processing with agent...",
        "tool_execution_task": "Executing tools...",
        "agent_with_tool_results_task": "Processing tool results...",
        "save_message_task": "Saving message...",
    }
    
    # Create thread-safe queue for events from callbacks
    event_queue = ThreadQueue()
    
    # Create event callback handler for streaming
    callback_handler = EventCallbackHandler(event_queue, status_messages)
    
    # Get checkpoint config
    thread_id = f"chat_session_{request.session_id}" if request.session_id else f"user_{request.user_id}"
    checkpoint_config = get_checkpoint_config(request.session_id) if request.session_id else {"configurable": {"thread_id": thread_id}}
    
    # Add callbacks to config
    if 'callbacks' not in checkpoint_config:
        checkpoint_config['callbacks'] = []
    checkpoint_config['callbacks'].append(callback_handler)
    
    # Add Langfuse CallbackHandler if enabled and trace_id is available
    # This captures LLM calls and associates them with the trace
    from app.agents.config import LANGFUSE_ENABLED
    if LANGFUSE_ENABLED and request.trace_id:
        try:
            from app.observability.tracing import get_callback_handler
            langfuse_callback = get_callback_handler()
            if langfuse_callback:
                checkpoint_config['callbacks'].append(langfuse_callback)
                logger.debug(f"[LANGFUSE] Added CallbackHandler to workflow for trace_id={request.trace_id}")
        except Exception as e:
            logger.warning(f"Failed to add Langfuse CallbackHandler: {e}", exc_info=True)
    
    # Track final response - use list for thread-safe sharing
    final_response_holder = [None]
    exception_holder = [None]
    
    # Run workflow in a thread (since stream() is sync)
    def run_workflow():
        try:
            # Use propagate_attributes to set trace context for Langfuse CallbackHandler
            # This ensures all LLM calls are associated with the trace
            from app.agents.config import LANGFUSE_ENABLED
            from langfuse import propagate_attributes
            from app.observability.tracing import prepare_trace_context
            
            if LANGFUSE_ENABLED and request.trace_id:
                # Create active workflow span using start_as_current_observation
                # This makes it the active observation in OpenTelemetry context
                # The CallbackHandler will automatically use this as the parent trace
                from langfuse import get_client
                langfuse = get_client()
                if langfuse:
                    # Prepare trace context for propagate_attributes
                    trace_context = prepare_trace_context(
                        user_id=request.user_id or 0,
                        session_id=request.session_id,
                        metadata={"trace_id": request.trace_id}  # Store trace_id in metadata for reference
                    )
                    
                    # Create active workflow span with trace_context - this makes it the active observation
                    with langfuse.start_as_current_observation(
                        as_type="span",
                        trace_context={"trace_id": request.trace_id},
                        name="ai_agent_workflow",
                        metadata={
                            "flow": request.flow,
                            "has_plan_steps": bool(request.plan_steps),
                            "user_id": str(request.user_id) if request.user_id else None,
                            "session_id": str(request.session_id) if request.session_id else None,
                        }
                    ) as workflow_span:
                        # Use propagate_attributes to propagate user_id, session_id, metadata to all child observations
                        with propagate_attributes(**trace_context):
                            # Use stream() to get state updates
                            # LangGraph Functional API stream() returns state dictionaries
                            # The final chunk should contain the AgentResponse
                            chunk_count = 0
                            for chunk in ai_agent_workflow.stream(request, config=checkpoint_config):
                                chunk_count += 1
                                logger.debug(f"[STREAM_CHUNK] Received chunk #{chunk_count}, type={type(chunk)}, keys={list(chunk.keys()) if isinstance(chunk, dict) else 'N/A'}")
                                
                                # chunk is a state dictionary
                                # The final chunk contains the AgentResponse
                                if isinstance(chunk, dict):
                                    # Check if this chunk contains the response
                                    # LangGraph Functional API may return response under different keys
                                    if 'ai_agent_workflow' in chunk:
                                        response_data = chunk['ai_agent_workflow']
                                        logger.debug(f"[STREAM_CHUNK] Found 'ai_agent_workflow' key, response_data type={type(response_data)}")
                                        if isinstance(response_data, AgentResponse):
                                            final_response_holder[0] = response_data
                                            logger.info(f"[STREAM_CHUNK] Extracted AgentResponse from 'ai_agent_workflow' key: agent={response_data.agent_name}, has_reply={bool(response_data.reply)}")
                                        elif isinstance(response_data, dict):
                                            # Try to construct AgentResponse from dict
                                            try:
                                                final_response_holder[0] = AgentResponse(**response_data)
                                                logger.info(f"[STREAM_CHUNK] Constructed AgentResponse from dict: agent={final_response_holder[0].agent_name}, has_reply={bool(final_response_holder[0].reply)}")
                                            except Exception as e:
                                                logger.warning(f"[STREAM_CHUNK] Failed to construct AgentResponse from dict: {e}")
                                    elif any(key in chunk for key in ['agent_name', 'reply', 'tool_calls', 'type']):
                                        # Might be the response directly as a dict
                                        try:
                                            final_response_holder[0] = AgentResponse(**chunk)
                                            logger.info(f"[STREAM_CHUNK] Constructed AgentResponse from chunk dict: agent={final_response_holder[0].agent_name}, has_reply={bool(final_response_holder[0].reply)}")
                                        except Exception as e:
                                            logger.warning(f"[STREAM_CHUNK] Failed to construct AgentResponse from chunk: {e}, chunk_keys={list(chunk.keys())}")
                                elif isinstance(chunk, AgentResponse):
                                    final_response_holder[0] = chunk
                                    logger.info(f"[STREAM_CHUNK] Chunk is AgentResponse directly: agent={chunk.agent_name}, has_reply={bool(chunk.reply)}")
                            
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
            else:
                # No Langfuse tracing - run without context managers
                chunk_count = 0
                for chunk in ai_agent_workflow.stream(request, config=checkpoint_config):
                    chunk_count += 1
                    logger.debug(f"[STREAM_CHUNK] Received chunk #{chunk_count}, type={type(chunk)}, keys={list(chunk.keys()) if isinstance(chunk, dict) else 'N/A'}")
                    
                    # chunk is a state dictionary
                    # The final chunk contains the AgentResponse
                    if isinstance(chunk, dict):
                        # Check if this chunk contains the response
                        # LangGraph Functional API may return response under different keys
                        if 'ai_agent_workflow' in chunk:
                            response_data = chunk['ai_agent_workflow']
                            logger.debug(f"[STREAM_CHUNK] Found 'ai_agent_workflow' key, response_data type={type(response_data)}")
                            if isinstance(response_data, AgentResponse):
                                final_response_holder[0] = response_data
                                logger.info(f"[STREAM_CHUNK] Extracted AgentResponse from 'ai_agent_workflow' key: agent={response_data.agent_name}, has_reply={bool(response_data.reply)}")
                            elif isinstance(response_data, dict):
                                # Try to construct AgentResponse from dict
                                try:
                                    final_response_holder[0] = AgentResponse(**response_data)
                                    logger.info(f"[STREAM_CHUNK] Constructed AgentResponse from dict: agent={final_response_holder[0].agent_name}, has_reply={bool(final_response_holder[0].reply)}")
                                except Exception as e:
                                    logger.warning(f"[STREAM_CHUNK] Failed to construct AgentResponse from dict: {e}")
                        elif isinstance(chunk, AgentResponse):
                            final_response_holder[0] = chunk
                            logger.info(f"[STREAM_CHUNK] Chunk is AgentResponse directly: agent={chunk.agent_name}, has_reply={bool(chunk.reply)}")
                        elif any(key in chunk for key in ['agent_name', 'reply', 'tool_calls', 'type']):
                            # Might be the response directly as a dict
                            try:
                                final_response_holder[0] = AgentResponse(**chunk)
                                logger.info(f"[STREAM_CHUNK] Constructed AgentResponse from chunk dict: agent={final_response_holder[0].agent_name}, has_reply={bool(final_response_holder[0].reply)}")
                            except Exception as e:
                                logger.warning(f"[STREAM_CHUNK] Failed to construct AgentResponse from chunk: {e}, chunk_keys={list(chunk.keys())}")
                    elif isinstance(chunk, AgentResponse):
                        final_response_holder[0] = chunk
                        logger.info(f"[STREAM_CHUNK] Chunk is AgentResponse directly: agent={chunk.agent_name}, has_reply={bool(chunk.reply)}")
                
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
                logger.info(f"[EVENT_QUEUE] Consumed event #{events_yielded} type={event_type} (queue_size={event_queue.qsize()})")
                if event_type == "token":
                    logger.debug(f"[EVENT_QUEUE] Token value: {event.get('value', '')[:30]}...")
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
