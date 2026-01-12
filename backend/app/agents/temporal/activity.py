"""
Temporal activities for running LangGraph workflows and publishing to Redis.
"""
import json
import asyncio
from temporalio import activity
from typing import Dict, Any
from app.agents.runner import AgentRunner
from app.core.redis import get_redis_client
from app.core.logging import get_logger

logger = get_logger(__name__)


def _handle_publish_task_done(task: asyncio.Task, event_type: str, event_count: int) -> None:
    """Callback to handle publish task completion and log errors."""
    try:
        if task.exception():
            logger.error(f"[REDIS_PUBLISH] Publish task failed for {event_type} (event_count={event_count}): {task.exception()}", exc_info=True)
    except Exception:
        pass  # Ignore errors in callback


async def _serialize_event(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    Serialize event for Redis publishing, handling Pydantic models.
    
    Args:
        event: Event dictionary
        
    Returns:
        Serializable event dictionary
    """
    serializable_event = event.copy() if isinstance(event, dict) else event
    
    # Convert AgentResponse objects to dicts
    if isinstance(serializable_event, dict) and "response" in serializable_event:
        response = serializable_event["response"]
        if hasattr(response, 'model_dump'):  # Pydantic v2
            serializable_event["response"] = response.model_dump()
        elif hasattr(response, 'dict'):  # Pydantic v1
            serializable_event["response"] = response.dict()
    
    return serializable_event


async def _publish_event_async(
    redis_client,
    channel: str,
    event: Dict[str, Any],
    event_count: int
) -> None:
    """
    Background task for non-blocking Redis publish.
    
    Args:
        redis_client: Redis client instance
        channel: Redis channel name
        event: Event dictionary to publish
        event_count: Event count for logging
    """
    try:
        serializable_event = await _serialize_event(event)
        event_json = json.dumps(serializable_event, default=str)
        await redis_client.publish(channel, event_json.encode('utf-8'))
        
        event_type = event.get('type', 'unknown')
        if event_type == "token":
            logger.info(f"[REDIS_PUBLISH] Published token event to {channel} (event_count={event_count}): {event.get('value', '')[:30]}...")
        else:
            logger.info(f"[REDIS_PUBLISH] Published event type={event_type} to {channel} (event_count={event_count})")
    except Exception as e:
        logger.error(f"[REDIS_PUBLISH] Error in background publish: {e}", exc_info=True)


@activity.defn
async def run_chat_activity(input_data: Any) -> Dict[str, Any]:
    """
    Activity that runs LangGraph workflow and publishes events to Redis.
    
    Implements Temporal best practices:
    - Activity heartbeating for long-running operations
    - Proper error handling and reporting
    - Progress tracking via heartbeats
    
    Args:
        input_data: ChatActivityInput dataclass containing:
            - chat_id: Chat session ID
            - state: Workflow state containing:
                - user_id: User ID
                - session_id: Chat session ID
                - message: User message
                - plan_steps: Optional plan steps
                - flow: Flow type (main, plan, etc.)
                - tenant_id: Optional tenant ID for Redis channel
            
    Returns:
        Dictionary with status and final state
    """
    # Extract values from input dataclass (Temporal may serialize it to dict)
    if isinstance(input_data, dict):
        chat_id = input_data.get("chat_id")
        state = input_data.get("state", {})
    else:
        # It's a dataclass instance
        chat_id = input_data.chat_id
        state = input_data.state
    
    # Extract message and other parameters from state
    message = state.get("message", "")
    user_id = state.get("user_id")
    session_id = state.get("session_id", chat_id)
    
    logger.info(f"[ACTIVITY_START] Starting activity for chat_id={chat_id}, message_preview={message[:50] if message else '(empty)'}..., user_id={user_id}, session_id={session_id}, state_keys={list(state.keys())}")
    
    if not message:
        logger.error(f"[ACTIVITY_ERROR] No message in state for chat_id={chat_id}. State keys: {list(state.keys())}")
        return {
            "status": "error",
            "error": "No message provided",
            "event_count": 0
        }
    
    redis_client = None
    try:
        # Get Redis client with error handling
        try:
            redis_client = await get_redis_client()
        except Exception as e:
            logger.error(f"Failed to get Redis client for chat_id={chat_id}: {e}", exc_info=True)
            # Continue without Redis - workflow will still execute but events won't be published
            redis_client = None
        
        # Build Redis channel name - handle None values properly
        # CRITICAL: Use user_id as tenant_id if tenant_id is missing to match SSE subscription
        # SSE endpoint subscribes to chat:{user.id}:{chat_id}, so we must publish to the same channel
        tenant_id = state.get("tenant_id") or state.get("user_id")
        if not tenant_id:
            logger.error(
                f"[ACTIVITY_CHANNEL] CRITICAL: No tenant_id or user_id in state for chat_id={chat_id}. "
                f"State keys: {list(state.keys())}. This will cause channel mismatch and frontend won't receive tokens!"
            )
            # This should never happen if workflow_manager and workflow are correct
            # But we'll raise an error to make it obvious rather than silently using 'default'
            raise ValueError(
                f"Cannot determine Redis channel for chat_id={chat_id}: missing user_id/tenant_id in state. "
                f"State keys: {list(state.keys())}"
            )
        tenant_id = str(tenant_id)  # Ensure it's a string
        channel = f"chat:{tenant_id}:{chat_id}"
        
        logger.info(f"Starting chat activity for chat_id={chat_id}, channel={channel} (tenant_id={tenant_id}, user_id={state.get('user_id')})")
        
        # Send initial heartbeat to indicate activity has started
        activity.heartbeat({"status": "initialized", "chat_id": chat_id})
        
        # Create root Langfuse trace if enabled (for activity-level tracing)
        trace_id = None
        langfuse_trace = None
        from app.agents.config import LANGFUSE_ENABLED
        if LANGFUSE_ENABLED:
            try:
                from langfuse import get_client
                import uuid
                langfuse = get_client()
                if langfuse:
                    # Generate deterministic trace ID
                    user_id = state.get("user_id")
                    trace_seed = f"{chat_id}-{user_id}-{uuid.uuid4()}"
                    trace_id = langfuse.create_trace_id(seed=trace_seed) if hasattr(langfuse, 'create_trace_id') else str(uuid.uuid4())
                    
                    # Create root trace using start_observation with trace_context
                    # Use trace_context to set the trace_id - this creates/associates with the trace
                    # Use as_type="span" for the root observation (trace is created automatically)
                    # user_id and session_id are stored in metadata for trace identification
                    langfuse_trace = langfuse.start_observation(
                        as_type="span",
                        trace_context={"trace_id": trace_id},
                        name="chat_activity",
                        metadata={
                            "chat_id": chat_id,
                            "user_id": str(user_id) if user_id else None,
                            "session_id": str(chat_id) if chat_id else None,
                            "flow": state.get("flow", "main"),
                        }
                    )
                    logger.info(f"[LANGFUSE] Created root trace id={trace_id} for chat_id={chat_id}")
            except Exception as e:
                logger.warning(f"Failed to create Langfuse trace: {e}", exc_info=True)
        
        # Create AgentRunner - this handles request building, trace context, etc.
        runner = AgentRunner(
            user_id=state.get("user_id"),
            chat_session_id=chat_id,
            message=state.get("message", ""),
            plan_steps=state.get("plan_steps"),
            flow=state.get("flow", "main"),
            trace_id=trace_id,  # Pass activity-generated trace_id to runner
            org_slug=state.get("org_slug"),
            org_roles=state.get("org_roles", []),
            app_roles=state.get("app_roles", []),
        )
        
        final_response = None
        event_count = [0]  # Use list for mutable closure
        publish_tasks = []  # Track publish tasks to ensure they execute
        
        # Run workflow using AgentRunner.stream()
        # Publish to Redis directly in the loop (non-blocking) to ensure tasks execute properly
        async for event in runner.stream():
            event_type = event.get('type', 'unknown')
            
            # Log token events to verify they reach the activity loop (INFO level for debugging)
            if event_type == "token":
                logger.info(f"[ACTIVITY_LOOP] Received token event in activity loop (value_preview={event.get('value', '')[:30]}...)")
            
            # Check for cancellation request from Temporal
            if activity.is_cancelled():
                logger.info(f"Activity cancelled for chat_id={chat_id}")
                activity.heartbeat({"status": "cancelled", "chat_id": chat_id})
                return {
                    "status": "cancelled",
                }
            
            event_count[0] += 1
            
            # Publish event to Redis (fire-and-forget, non-blocking)
            if redis_client:
                # Create background task for non-blocking publish
                current_count = event_count[0]
                try:
                    task = asyncio.create_task(_publish_event_async(redis_client, channel, event, current_count))
                    publish_tasks.append(task)
                    # Add error callback to track task failures
                    task.add_done_callback(lambda t, et=event_type, ec=current_count: _handle_publish_task_done(t, et, ec))
                    # Log token events to verify they're being scheduled (INFO level for debugging)
                    if event_type == "token":
                        logger.info(f"[REDIS_SCHEDULE] Scheduled token publish task (event_count={current_count})")
                    # Yield control to event loop to allow background tasks to execute
                    # This ensures publish tasks can run even in tight loops
                    await asyncio.sleep(0)
                except Exception as e:
                    logger.error(f"[REDIS_PUBLISH] Failed to create publish task for {event_type} (event_count={current_count}): {e}", exc_info=True)
            else:
                if event_type == "token":
                    logger.debug(f"[REDIS_PUBLISH] Redis client not available, skipping token publish")
            
            # Send heartbeat periodically (every 10 events or on important events)
            if event_count[0] % 10 == 0 or event.get("type") in ["final", "interrupt", "error"]:
                activity.heartbeat({
                    "status": "processing",
                    "chat_id": chat_id,
                    "event_count": event_count[0],
                    "last_event_type": event.get("type"),
                })
            
            # Check for interrupt
            if event.get("type") == "interrupt":
                logger.info(f"Workflow interrupted for chat_id={chat_id}")
                activity.heartbeat({"status": "interrupted", "chat_id": chat_id})
                return {
                    "status": "interrupted",
                    "interrupt_reason": event.get("reason"),
                }
            
            # Capture final response (for message_saved event)
            if event.get("type") == "final":
                final_response = event.get("response")
        
        # Emit message_saved event for assistant message after final event
        # The message should already be saved by save_message_task during workflow execution
        # Use fire-and-forget pattern for this as well
        if final_response and redis_client and chat_id:
            try:
                # Query the latest assistant message for this session (use sync_to_async for Django ORM in async context)
                from app.db.models.message import Message
                from asgiref.sync import sync_to_async
                
                latest_assistant_message = await sync_to_async(
                    lambda: Message.objects.filter(
                        session_id=chat_id,
                        role="assistant"
                    ).order_by('-created_at').first()
                )()
                
                if latest_assistant_message:
                    message_saved_event = {
                        "type": "message_saved",
                        "data": {
                            "role": "assistant",
                            "db_id": latest_assistant_message.id,
                            "session_id": chat_id,
                        }
                    }
                    # Use fire-and-forget for message_saved event too
                    asyncio.create_task(_publish_event_async(redis_client, channel, message_saved_event, event_count[0] + 1))
                    logger.info(f"[MESSAGE_SAVED_EVENT] Emitted assistant message_saved event db_id={latest_assistant_message.id} session={chat_id}")
                else:
                    logger.warning(f"[MESSAGE_SAVED_EVENT] No assistant message found for session={chat_id} after final event")
            except Exception as e:
                logger.warning(f"Failed to emit message_saved event for assistant message: {e}", exc_info=True)
        
        # End Langfuse trace if created and flush traces
        if langfuse_trace:
            try:
                langfuse_trace.end()
                logger.debug(f"[LANGFUSE] Ended trace id={trace_id}")
            except Exception as e:
                logger.warning(f"Failed to end Langfuse trace: {e}", exc_info=True)
        
        # Flush Langfuse traces to ensure they're sent
        if LANGFUSE_ENABLED:
            try:
                from app.observability.tracing import flush_traces
                flush_traces()
                logger.debug(f"[LANGFUSE] Flushed traces for chat_id={chat_id}")
            except Exception as e:
                logger.warning(f"Failed to flush Langfuse traces: {e}", exc_info=True)
        
        # Send final heartbeat
        activity.heartbeat({"status": "completed", "chat_id": chat_id, "event_count": event_count[0]})
        logger.info(f"Chat activity completed for chat_id={chat_id}")
        
        # Return minimal payload - streaming events go via Redis, workflow already has state
        return {
            "status": "completed",
            "has_response": bool(final_response),
        }
    except Exception as e:
        logger.error(f"Error in chat activity for chat_id={chat_id}: {e}", exc_info=True)
        
        # End Langfuse trace on error if created
        if 'langfuse_trace' in locals() and langfuse_trace:
            try:
                langfuse_trace.end()
            except Exception:
                pass  # Ignore trace ending errors during error handling
        
        # Send heartbeat on error
        try:
            activity.heartbeat({"status": "error", "chat_id": chat_id, "error": str(e)})
        except Exception:
            pass  # Ignore heartbeat errors during error handling
        
        # Return minimal error payload
        return {
            "status": "error",
            "error": str(e),
        }
