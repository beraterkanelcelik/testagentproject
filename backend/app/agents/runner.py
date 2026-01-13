"""
Agent execution and event streaming using LangGraph Functional API.

This module provides a unified AgentRunner class that handles both streaming
and non-streaming execution, with the stream/non-stream switch at the API layer.
"""
import uuid
import os
import asyncio
from typing import Dict, Any, Iterator, Optional, List, AsyncIterator, Callable
from app.agents.functional.workflow import ai_agent_workflow_events
from app.agents.functional.models import AgentRequest, AgentResponse
from app.agents.config import LANGCHAIN_TRACING_V2, LANGCHAIN_PROJECT, LANGFUSE_ENABLED
from app.core.logging import get_logger
from app.observability.tracing import prepare_trace_context, flush_traces

logger = get_logger(__name__)

# Enable LangSmith tracing if configured (optional, for compatibility)
if LANGCHAIN_TRACING_V2:
    os.environ['LANGCHAIN_TRACING_V2'] = 'true'
    os.environ['LANGCHAIN_PROJECT'] = LANGCHAIN_PROJECT


def serialize_response(response: AgentResponse) -> Dict[str, Any]:
    """
    Serialize AgentResponse to dict for JSON transport.
    
    Args:
        response: AgentResponse object or None
        
    Returns:
        Dictionary representation of the response, or None if response is None
    """
    if response is None:
        return None
    if hasattr(response, 'model_dump'):
        return response.model_dump()
    elif hasattr(response, 'dict'):
        return response.dict()
    elif isinstance(response, dict):
        return response
    else:
        return {"reply": str(response)}


class AgentRunner:
    """
    Unified runner for agent execution that handles both streaming and non-streaming modes.
    
    The stream/non-stream switch is handled by calling either run() or stream(),
    keeping the graph logic stream-agnostic.
    """
    
    def __init__(
        self,
        user_id: int,
        chat_session_id: int,
        message: str,
        plan_steps: Optional[List[Dict[str, Any]]] = None,
        flow: str = "main",
        trace_id: Optional[str] = None,
        org_slug: Optional[str] = None,
        org_roles: Optional[List[str]] = None,
        app_roles: Optional[List[str]] = None,
        resume_payload: Optional[Any] = None,
        run_id: Optional[str] = None,
        parent_message_id: Optional[int] = None
    ):
        """
        Initialize the agent runner.
        
        Args:
            user_id: User ID
            chat_session_id: Chat session ID
            message: User message
            plan_steps: Optional plan steps
            flow: Flow type
            trace_id: Optional pre-generated trace ID (for Temporal workflows)
            org_slug: Optional organization slug
            org_roles: Optional organization roles
            app_roles: Optional application roles
            resume_payload: Optional resume payload for LangGraph interrupt resume (Command(resume=...))
        """
        self.user_id = user_id
        self.chat_session_id = chat_session_id
        self.message = message
        self.plan_steps = plan_steps
        self.flow = flow
        self.resume_payload = resume_payload
        
        # Generate trace ID if not provided
        if trace_id:
            self.trace_id = trace_id
        else:
            from langfuse import get_client
            langfuse = get_client() if LANGFUSE_ENABLED else None
            if langfuse:
                trace_seed = f"{chat_session_id}-{user_id}-{uuid.uuid4()}"
                self.trace_id = langfuse.create_trace_id(seed=trace_seed)
            else:
                self.trace_id = str(uuid.uuid4())
        
        # Build request or Command for resume
        # If resume_payload is provided, use Command(resume=...) instead of AgentRequest
        if resume_payload is not None:
            from langgraph.types import Command
            self.request = Command(resume=resume_payload)
        else:
            self.request = AgentRequest(
                query=message,
                session_id=chat_session_id,
                user_id=user_id,
                org_slug=org_slug,
                org_roles=org_roles or [],
                app_roles=app_roles or [],
                flow=flow,
                plan_steps=plan_steps,
                trace_id=self.trace_id,
                run_id=run_id,
                parent_message_id=parent_message_id,
            )
        
        # Prepare trace context
        self.trace_context = None
        if LANGFUSE_ENABLED:
            self.trace_context = prepare_trace_context(
                user_id=user_id,
                session_id=chat_session_id,
                metadata={
                    "chat_session_id": chat_session_id,
                    "trace_id": self.trace_id,
            }
        )
    
    async def execute(self) -> AsyncIterator[Dict[str, Any]]:
        """
        Single execution pipeline - yields all events from ai_agent_workflow_events().
        
        This is the unified event source for both stream and non-stream modes.
        The difference is only in how events are delivered (forwarded vs aggregated).
        
        Yields:
            Event dictionaries with type and data
        """
        try:
            async for event in ai_agent_workflow_events(
                self.request,
                session_id=self.chat_session_id,
                user_id=self.user_id,
                trace_id=self.trace_id
            ):
                yield event
                if event.get("type") in ("final", "interrupt", "error"):
                    return
        except Exception as e:
            logger.error(
                f"Error in AgentRunner.execute for user {self.user_id}, session {self.chat_session_id}: {e}",
                exc_info=True
            )
            yield {"type": "error", "error": str(e)}
    
    async def run(self) -> AgentResponse:
        """
        Run workflow in non-streaming mode, collecting events and returning final response.
        
        Returns:
            Final AgentResponse
            
        Raises:
            Exception: If workflow completes without final response or encounters an error
        """
        final = None
        
        # Execute with trace context if enabled
        # Pass session_id, user_id, trace_id separately to handle Command type
        # NOTE: Langfuse context is already managed inside ai_agent_workflow_events.run_workflow()
        # We don't need to wrap it here again - doing so can cause context detach errors on interrupt
        if LANGFUSE_ENABLED and self.trace_context:
            # Just pass trace context - let ai_agent_workflow_events handle Langfuse context internally
            async for event in ai_agent_workflow_events(
                self.request,
                session_id=self.chat_session_id,
                user_id=self.user_id,
                trace_id=self.trace_id
            ):
                if event.get("type") == "final":
                    final = event.get("response")
                elif event.get("type") == "interrupt":
                    # Interrupt is terminal - workflow paused for approval
                    raise Exception("Workflow interrupted - requires resume")
                elif event.get("type") == "error":
                    raise Exception(event.get("error", "Unknown error"))
        else:
            async for event in ai_agent_workflow_events(
                self.request,
                session_id=self.chat_session_id,
                user_id=self.user_id,
                trace_id=self.trace_id
            ):
                if event.get("type") == "final":
                    final = event.get("response")
                elif event.get("type") == "interrupt":
                    # Interrupt is terminal - workflow paused for approval
                    raise Exception("Workflow interrupted - requires resume")
                elif event.get("type") == "error":
                    raise Exception(event.get("error", "Unknown error"))
        
        if final is None:
            raise Exception("Workflow completed without final response")
        
        # Flush traces if enabled
        if LANGFUSE_ENABLED:
            flush_traces()
        
        return final
    
    async def invoke(self) -> Dict[str, Any]:
        """
        Invoke workflow in non-streaming mode using LangGraph's .invoke() method.
        
        This method is used inside Temporal activity for non-stream mode.
        It does not generate token events, eliminating streaming overhead.
        
        Returns:
            Dictionary with status and response:
            - {"status": "completed", "response": AgentResponse} on success
            - {"status": "approval_required", "interrupt": {...}} on interrupt
        """
        from app.agents.functional.workflow import ai_agent_workflow
        from app.agents.checkpoint import get_checkpoint_config
        from langgraph.errors import GraphInterrupt
        
        try:
            # Get checkpoint config for this session
            checkpoint_config = get_checkpoint_config(self.chat_session_id)
            
            # Call workflow directly with .invoke() (no streaming, no token events)
            # NOTE: When using .invoke(), interrupts are NOT raised as GraphInterrupt exceptions.
            # Instead, the result contains __interrupt__ key when interrupt() is called.
            # Reference: https://docs.langchain.com/oss/python/langgraph/interrupts
            result = ai_agent_workflow.invoke(self.request, config=checkpoint_config)
            
            # Check if result contains __interrupt__ (LangGraph's way of surfacing interrupts in .invoke())
            # When interrupt() is called, .invoke() returns a dict with __interrupt__ key instead of raising GraphInterrupt
            if isinstance(result, dict) and "__interrupt__" in result:
                interrupt_raw = result["__interrupt__"]
                interrupt_data = None
                
                # Extract interrupt value from LangGraph Interrupt object
                # LangGraph returns __interrupt__ as a tuple: (Interrupt(value={...}, id='...'),)
                if isinstance(interrupt_raw, tuple) and len(interrupt_raw) > 0:
                    interrupt_obj = interrupt_raw[0]
                    if hasattr(interrupt_obj, 'value'):
                        interrupt_data = interrupt_obj.value
                    elif isinstance(interrupt_obj, dict):
                        interrupt_data = interrupt_obj.get('value', interrupt_obj)
                    else:
                        interrupt_data = interrupt_obj
                elif isinstance(interrupt_raw, dict):
                    interrupt_data = interrupt_raw.get('value', interrupt_raw)
                elif hasattr(interrupt_raw, 'value'):
                    interrupt_data = interrupt_raw.value
                else:
                    interrupt_data = interrupt_raw
                
                logger.info(f"[HITL] [INVOKE] Workflow interrupted during invoke (via __interrupt__): session={self.chat_session_id}, interrupt_data={interrupt_data}")
                
                # Flush traces even on interrupt
                if LANGFUSE_ENABLED:
                    flush_traces()
                
                return {
                    "status": "approval_required",
                    "interrupt": interrupt_data or {"type": "tool_approval", "session_id": self.chat_session_id, "tools": []}
                }
            
            # result is AgentResponse (normal completion)
            if result:
                # Flush traces if enabled
                if LANGFUSE_ENABLED:
                    flush_traces()
                
                return {
                    "status": "completed",
                    "response": result
                }
            else:
                raise Exception("Workflow completed without response")
                
        except GraphInterrupt as e:
            # GraphInterrupt can still be raised in some edge cases, handle it for safety
            logger.info(f"[INVOKE] Caught GraphInterrupt exception: {type(e)}, has_value={hasattr(e, 'value')}, has_interrupt={hasattr(e, 'interrupt')}")
            # Interrupt occurred - workflow paused for approval
            # Extract interrupt data from the exception
            interrupt_data = None
            if hasattr(e, 'value'):
                interrupt_data = e.value
            elif hasattr(e, 'interrupt'):
                interrupt_data = e.interrupt
            
            logger.info(f"[HITL] [INVOKE] Workflow interrupted during invoke (via exception): session={self.chat_session_id}")
            
            # Flush traces even on interrupt
            if LANGFUSE_ENABLED:
                flush_traces()
            
            return {
                "status": "approval_required",
                "interrupt": interrupt_data or {"type": "tool_approval", "session_id": self.chat_session_id, "tools": []}
            }
        except Exception as e:
            logger.error(
                f"Error in AgentRunner.invoke for user {self.user_id}, session {self.chat_session_id}: {e}",
                exc_info=True
            )
            
            # Flush traces even on error
            if LANGFUSE_ENABLED:
                flush_traces()
            
            raise
    
    async def stream(self, emit: Optional[Callable[[Dict[str, Any]], None]] = None) -> AsyncIterator[Dict[str, Any]]:
        """
        Stream agent execution events.
        
        Args:
            emit: Optional callback function to call for each event (for Temporal/Redis)
            
        Yields:
            Event dictionaries with type and data
        """
        accumulated_content = ""
        tokens_used = 0
        
        try:
            # Execute with trace context if enabled
            # Pass session_id, user_id, trace_id separately to handle Command type
            # NOTE: Langfuse context is already managed inside ai_agent_workflow_events.run_workflow()
            # We don't need to wrap it here again - doing so can cause context detach errors on interrupt
            if LANGFUSE_ENABLED and self.trace_context:
                # Just pass trace context - let ai_agent_workflow_events handle Langfuse context internally
                async for event in ai_agent_workflow_events(
                    self.request,
                    session_id=self.chat_session_id,
                    user_id=self.user_id,
                    trace_id=self.trace_id
                ):
                    event_type = event.get("type", "unknown")
                    
                    # Accumulate tokens for done event
                    if event_type == "token":
                        accumulated_content += event.get("value", "")
                    
                    # Emit to callback if provided (for Temporal/Redis)
                    if emit:
                        emit(event)
                    
                    # Yield event
                    yield event
                    
                    # Check for terminal events
                    if event_type == "final":
                        response = event.get("response")
                        if response and hasattr(response, 'token_usage'):
                            tokens_used = response.token_usage.get("total_tokens", 0)
                        break
                    elif event_type == "interrupt":
                        # Interrupt is terminal - workflow paused for approval
                        break
                    elif event_type == "error":
                        break
            else:
                async for event in ai_agent_workflow_events(
                    self.request,
                    session_id=self.chat_session_id,
                    user_id=self.user_id,
                    trace_id=self.trace_id
                ):
                    event_type = event.get("type", "unknown")
                    
                    # Accumulate tokens for done event
                    if event_type == "token":
                        accumulated_content += event.get("value", "")
                    
                    # Emit to callback if provided (for Temporal/Redis)
                    if emit:
                        emit(event)
                    
                    # Yield event
                    yield event
                    
                    # Check for terminal events
                    if event_type == "final":
                        response = event.get("response")
                        if response and hasattr(response, 'token_usage'):
                            tokens_used = response.token_usage.get("total_tokens", 0)
                        break
                    elif event_type == "interrupt":
                        # Interrupt is terminal - workflow paused for approval
                        break
                    elif event_type == "error":
                        break
            
            # Flush traces if enabled
            if LANGFUSE_ENABLED:
                flush_traces()
            
            # Yield completion event
            yield {
                "type": "done",
                "data": {
                    "final_text": accumulated_content,
                    "tokens_used": tokens_used,
                    "trace_id": self.trace_id,
                }
            }
            
        except Exception as e:
            logger.error(
                f"Error in AgentRunner.stream for user {self.user_id}, session {self.chat_session_id}: {e}",
                exc_info=True
            )
            
            # Flush traces even on error
            if LANGFUSE_ENABLED:
                flush_traces()
            
            yield {
                "type": "error",
                "data": {
                    "error": str(e),
                    "trace_id": self.trace_id,
                }
            }


# ============================================================================
# API Layer Functions (Stream Switch Point)
# ============================================================================

def execute_agent(
    user_id: int,
    chat_session_id: int,
    message: str,
    plan_steps: Optional[List[Dict[str, Any]]] = None,
    flow: str = "main"
) -> Dict[str, Any]:
    """
    Execute agent using Functional API with input message (non-streaming).
    
    This is the API layer switch point for non-streaming execution.
    
    Args:
        user_id: User ID
        chat_session_id: Chat session ID
        message: User message
        plan_steps: Optional plan steps
        flow: Flow type
        
    Returns:
        Dictionary with execution results
    """
    runner = AgentRunner(
        user_id=user_id,
        chat_session_id=chat_session_id,
        message=message,
        plan_steps=plan_steps,
        flow=flow
    )
    
    try:
        logger.info(f"Executing agent for user {user_id}, session {chat_session_id}, trace: {runner.trace_id}")
        
        # Run in non-streaming mode
        response = asyncio.run(runner.run())
        
        logger.info(f"Agent execution completed successfully. Agent: {response.agent_name}")
        
        result = {
            "success": True,
            "response": response.reply or "",
            "agent": response.agent_name,
            "tool_calls": response.tool_calls,
            "trace_id": runner.trace_id,
        }
        
        # Include type and plan if this is a plan_proposal response
        if response.type == "plan_proposal":
            result["type"] = "plan_proposal"
            if response.plan:
                result["plan"] = response.plan
        
        # Include clarification and raw_tool_outputs if present
        if response.clarification:
            result["clarification"] = response.clarification
        
        if response.raw_tool_outputs:
            result["raw_tool_outputs"] = response.raw_tool_outputs
        
        return result
    except Exception as e:
        logger.error(
            f"Error executing agent for user {user_id}, session {chat_session_id}: {e}",
            exc_info=True
        )
        
        return {
            "success": False,
            "error": str(e),
            "response": f"I apologize, but I encountered an error: {str(e)}",
            "trace_id": runner.trace_id,
        }


async def stream_agent_events_async(
    user_id: int,
    chat_session_id: int,
    message: str,
    plan_steps: Optional[List[Dict[str, Any]]] = None,
    flow: str = "main"
) -> AsyncIterator[Dict[str, Any]]:
    """
    Stream agent execution events using event-based workflow.
    
    This is the API layer switch point for streaming execution.
    
    Args:
        user_id: User ID
        chat_session_id: Chat session ID
        message: User message
        plan_steps: Optional plan steps
        flow: Flow type
        
    Yields:
        Event dictionaries with type and data
    """
    runner = AgentRunner(
        user_id=user_id,
        chat_session_id=chat_session_id,
        message=message,
        plan_steps=plan_steps,
        flow=flow
    )
    
    logger.info(f"Streaming agent events for user {user_id}, session {chat_session_id}, trace: {runner.trace_id}, flow: {flow}")
    
    # Stream events
    async for event in runner.stream():
        yield event
