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
        app_roles: Optional[List[str]] = None
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
        """
        self.user_id = user_id
        self.chat_session_id = chat_session_id
        self.message = message
        self.plan_steps = plan_steps
        self.flow = flow
        
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
        
        # Build request
        self.request = AgentRequest(
            query=message,
            session_id=chat_session_id,
            user_id=user_id,
            org_slug=org_slug,
            org_roles=org_roles or [],
            app_roles=app_roles or [],
            flow=flow,
            plan_steps=plan_steps,
            trace_id=self.trace_id
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
        if LANGFUSE_ENABLED and self.trace_context:
            from langfuse import propagate_attributes
            with propagate_attributes(**self.trace_context):
                async for event in ai_agent_workflow_events(self.request):
                    if event.get("type") == "final":
                        final = event.get("response")
                    elif event.get("type") == "error":
                        raise Exception(event.get("error", "Unknown error"))
        else:
            async for event in ai_agent_workflow_events(self.request):
                if event.get("type") == "final":
                    final = event.get("response")
                elif event.get("type") == "error":
                    raise Exception(event.get("error", "Unknown error"))
        
        if final is None:
            raise Exception("Workflow completed without final response")
        
        # Flush traces if enabled
        if LANGFUSE_ENABLED:
            flush_traces()
        
        return final
    
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
            if LANGFUSE_ENABLED and self.trace_context:
                from langfuse import propagate_attributes
                with propagate_attributes(**self.trace_context):
                    async for event in ai_agent_workflow_events(self.request):
                        event_type = event.get("type", "unknown")
                        
                        # Accumulate tokens for done event
                        if event_type == "token":
                            accumulated_content += event.get("value", "")
                            # Log token events in runner to verify they're yielded (INFO for debugging)
                            logger.info(f"[RUNNER_STREAM] Yielding token event (value_preview={event.get('value', '')[:30]}...)")
                        
                        # Emit to callback if provided (for Temporal/Redis)
                        if emit:
                            emit(event)
                        
                        # Yield event
                        yield event
                        
                        # Check for final event
                        if event.get("type") == "final":
                            response = event.get("response")
                            if response and hasattr(response, 'token_usage'):
                                tokens_used = response.token_usage.get("total_tokens", 0)
                            break
                        elif event.get("type") == "error":
                            break
            else:
                async for event in ai_agent_workflow_events(self.request):
                    event_type = event.get("type", "unknown")
                    
                    # Accumulate tokens for done event
                    if event_type == "token":
                        accumulated_content += event.get("value", "")
                        # Log token events in runner to verify they're yielded (INFO for debugging)
                        logger.info(f"[RUNNER_STREAM] Yielding token event (value_preview={event.get('value', '')[:30]}...)")
                    
                    # Emit to callback if provided (for Temporal/Redis)
                    if emit:
                        emit(event)
                    
                    # Yield event
                    yield event
                    
                    # Check for final event
                    if event.get("type") == "final":
                        response = event.get("response")
                        if response and hasattr(response, 'token_usage'):
                            tokens_used = response.token_usage.get("total_tokens", 0)
                        break
                    elif event.get("type") == "error":
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


def stream_agent_events(
    user_id: int,
    chat_session_id: int,
    message: str,
    plan_steps: Optional[List[Dict[str, Any]]] = None,
    flow: str = "main"
) -> Iterator[Dict[str, Any]]:
    """
    Synchronous wrapper for async stream_agent_events_async.
    
    ⚠️ NOTE: This is a temporary compatibility layer for Django sync views.
    When migrating to ASGI-only views and Redis/Temporal streaming, this function
    will be removed. Use stream_agent_events_async() instead.
    
    Uses asyncio to run the async generator in a new event loop.
    
    Args:
        user_id: User ID
        chat_session_id: Chat session ID
        message: User message
        plan_steps: Optional plan steps
        flow: Flow type
        
    Yields:
        Event dictionaries with type and data
    """
    async def _run_async():
        async for event in stream_agent_events_async(user_id, chat_session_id, message, plan_steps, flow):
            yield event
    
    # Run async generator in event loop
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            async_gen = _run_async()
            while True:
                try:
                    event = loop.run_until_complete(asyncio.wait_for(async_gen.__anext__(), timeout=600))
                    yield event
                    if event.get("type") in ["final", "error", "done"]:
                                                    break
                except StopAsyncIteration:
                                                break
                except asyncio.TimeoutError:
                    logger.warning("Timeout waiting for next event")
                    break
        finally:
            loop.close()
    except Exception as e:
        logger.error(f"Error in stream_agent_events wrapper: {e}", exc_info=True)
        yield {
            "type": "error",
            "data": {"error": str(e)}
        }
