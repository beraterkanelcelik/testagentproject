"""
Agent execution and event streaming using LangGraph Functional API.

This module provides AgentRunner class for streaming execution via SSE (Server-Sent Events).
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
    Runner for agent execution that handles streaming via SSE (Server-Sent Events).
    
    Uses the stream() method to generate events that are published to Redis for real-time streaming.
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
            # Execute workflow
            # Pass session_id, user_id, trace_id separately to handle Command type
            # NOTE: Langfuse context is already managed inside ai_agent_workflow_events.run_workflow()
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
# API Layer Functions
# ============================================================================

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
