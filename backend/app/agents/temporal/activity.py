"""
Temporal activities for running LangGraph workflows and publishing to Redis.
"""
import json
import os
import asyncio
from temporalio import activity
from typing import Dict, Any
from app.agents.runner import AgentRunner
from app.core.redis import get_redis_client
from app.core.logging import get_logger

logger = get_logger(__name__)


def _handle_publish_task_done(task: asyncio.Task, event_type: str, event_count: int, semaphore: asyncio.Semaphore) -> None:
    """
    Callback to handle publish task completion, log errors, and release semaphore.
    
    Args:
        task: Completed publish task
        event_type: Event type for logging
        event_count: Event count for logging
        semaphore: Semaphore to release
    """
    try:
        if task.exception():
            logger.error(f"[REDIS_PUBLISH] Publish task failed for {event_type} (event_count={event_count}): {task.exception()}", exc_info=True)
    except Exception:
        pass  # Ignore errors in callback
    finally:
        # Always release semaphore, even if there was an error
        try:
            semaphore.release()
        except Exception:
            pass  # Ignore semaphore release errors


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
        # Only log non-token events for debugging (token events are too verbose)
        if event_type != "token":
            logger.debug(f"[REDIS_PUBLISH] Published event type={event_type} to {channel} (event_count={event_count})")
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
    
    # Extract message and other parameters from state (common for both dict and dataclass paths)
    message = state.get("message", "")
    user_id = state.get("user_id")
    session_id = state.get("session_id", chat_id)
    mode = state.get("mode", "stream")  # Execution mode: "stream" or "non_stream"
    
    logger.info(f"[ACTIVITY_START] Starting activity for chat_id={chat_id}, mode={mode}, message_preview={message[:50] if message else '(empty)'}..., user_id={user_id}, session_id={session_id}, state_keys={list(state.keys())}")
    
    if not message:
        logger.error(f"[ACTIVITY_ERROR] No message in state for chat_id={chat_id}. State keys: {list(state.keys())}")
        return {
            "status": "error",
            "error": "No message provided",
            "event_count": 0
        }
    
    # Redis client and channel - will be initialized only for stream mode
    redis_client = None
    channel = None
    tenant_id = None
    try:
        
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
        
        # Check for resume_payload (from human-in-the-loop interrupt resume)
        resume_payload = state.get("resume_payload")
        if resume_payload:
            logger.info(f"[HITL] [ACTIVITY_RESUME] Activity re-run with resume_payload: session={chat_id}")
        
        # Create AgentRunner - this handles request building, trace context, etc.
        # If resume_payload is provided, runner will use Command(resume=...) instead of AgentRequest
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
            resume_payload=resume_payload,  # Pass resume_payload for interrupt resume
            run_id=state.get("run_id"),  # Correlation ID for /run polling
            parent_message_id=state.get("parent_message_id"),  # Parent message ID for correlation
        )
        
        if resume_payload:
            logger.info(f"[HITL] Injected resume_payload into AgentRunner: session={chat_id}")
        
        # Execute based on mode
        if mode == "non_stream":
            # Non-streaming mode: aggregate events internally, NO Redis
            # Uses same execute() pipeline as stream mode for consistency
            logger.info(f"[ACTIVITY] Executing in non-stream mode: session={chat_id}")
            
            final_response = None
            event_count = 0
            
            try:
                async for event in runner.execute():
                    event_count += 1
                    
                    # Send heartbeat periodically (every 10 events or on important events)
                    if event_count % 10 == 0 or event.get("type") in ["final", "interrupt", "error"]:
                        activity.heartbeat({
                            "status": "processing",
                            "chat_id": chat_id,
                            "event_count": event_count,
                            "last_event_type": event.get("type"),
                        })
                    
                    if event.get("type") == "final":
                        final_response = event.get("response")
                        # Message is saved by save_message_task in workflow (same as stream path)
                    elif event.get("type") == "interrupt":
                        interrupt_data = event.get("data") or event.get("interrupt")
                        logger.info(f"[HITL] [INTERRUPT] Workflow interrupted in non-stream mode for chat_id={chat_id}, interrupt_data={interrupt_data}")
                        activity.heartbeat({"status": "interrupted", "chat_id": chat_id})
                        
                        # Import serialize_response from runner
                        from app.agents.runner import serialize_response
                        
                        return {
                            "status": "interrupted",
                            "interrupt": interrupt_data,
                            "run_id": state.get("run_id")  # Include for correlation
                        }
                    elif event.get("type") == "error":
                        error_msg = event.get("error", "Unknown error")
                        logger.error(f"Error in non-stream execution for chat_id={chat_id}: {error_msg}")
                        activity.heartbeat({"status": "error", "chat_id": chat_id, "error": error_msg})
                        return {
                            "status": "error",
                            "error": error_msg,
                            "run_id": state.get("run_id")
                        }
                
                # Import serialize_response from runner
                from app.agents.runner import serialize_response
                
                if final_response is None:
                    raise Exception("Workflow completed without final response")
                
                logger.info(f"[ACTIVITY] Non-stream execution completed: session={chat_id}")
                
                # Send final heartbeat
                activity.heartbeat({"status": "completed", "chat_id": chat_id, "event_count": event_count})
                
                return {
                    "status": "completed",
                    "response": serialize_response(final_response),
                    "run_id": state.get("run_id")  # Include for correlation
                }
                    
            except Exception as e:
                logger.error(f"Error in non-stream execution for chat_id={chat_id}: {e}", exc_info=True)
                activity.heartbeat({"status": "error", "chat_id": chat_id, "error": str(e)})
                return {
                    "status": "error",
                    "error": str(e),
                    "run_id": state.get("run_id")
                }
        
        # Streaming mode: use .stream() and publish to Redis
        logger.info(f"[ACTIVITY] Executing in stream mode: session={chat_id}")
        
        # Initialize Redis and build channel for stream mode only (reduces overhead for non-stream)
        # CRITICAL: Use user_id as tenant_id if tenant_id is missing to match SSE subscription
        # SSE endpoint subscribes to chat:{user.id}:{chat_id}, so we must publish to the same channel
        tenant_id = state.get("tenant_id") or state.get("user_id")
        if not tenant_id:
            logger.error(
                f"[ACTIVITY_CHANNEL] CRITICAL: No tenant_id or user_id in state for chat_id={chat_id}. "
                f"State keys: {list(state.keys())}. This will cause channel mismatch and frontend won't receive tokens!"
            )
            raise ValueError(
                f"Cannot determine Redis channel for chat_id={chat_id}: missing user_id/tenant_id in state. "
                f"State keys: {list(state.keys())}"
            )
        tenant_id = str(tenant_id)  # Ensure it's a string
        channel = f"chat:{tenant_id}:{chat_id}"
        logger.info(f"Starting chat activity for chat_id={chat_id}, channel={channel} (tenant_id={tenant_id}, user_id={state.get('user_id')})")
        
        # Get Redis client
        try:
            redis_client = await get_redis_client()
        except Exception as e:
            logger.error(f"Failed to get Redis client for stream mode chat_id={chat_id}: {e}", exc_info=True)
            redis_client = None
        
        final_response = None
        event_count = [0]  # Use list for mutable closure
        interrupt_data = None  # Track interrupt data for resume
        
        # Semaphore for backpressure: cap concurrent publish operations
        # Prevents unbounded in-flight tasks if publish rate > completion rate
        # Only create for stream mode (non-stream doesn't publish)
        PUBLISH_CONCURRENCY_LIMIT = int(os.getenv('REDIS_PUBLISH_CONCURRENCY_LIMIT', '100'))
        publish_semaphore = asyncio.Semaphore(PUBLISH_CONCURRENCY_LIMIT)
        
        # Run workflow using AgentRunner.stream()
        # Publish to Redis directly in the loop (non-blocking) to ensure tasks execute properly
        async for event in runner.stream():
            event_type = event.get('type', 'unknown')
            
            # Check for cancellation request from Temporal
            # NOTE: Activity checks for cancellation from Temporal (workflow termination)
            # Client disconnect does NOT trigger activity cancellation
            # This ensures work completes even if user closes browser
            # Applies to both stream and non-stream modes
            if activity.is_cancelled():
                logger.info(f"Activity cancelled for chat_id={chat_id}")
                activity.heartbeat({"status": "cancelled", "chat_id": chat_id})
                return {
                    "status": "cancelled",
                }
            
            event_count[0] += 1
            
            # Publish event to Redis (fire-and-forget, non-blocking with backpressure)
            if redis_client:
                # DESIGN NOTE: Backpressure strategy
                # Current approach: semaphore throttles ALL events (including tokens)
                # - When Redis is slow, this slows down token consumption, which can slow upstream LLM streaming
                # - This protects the system from unbounded memory growth (current priority)
                # Alternative approach (for "best-effort tokens"): 
                # - Drop token events when semaphore saturated, but always publish interrupt/final/error
                # - This keeps LLM streaming fast but may drop some tokens under load
                # Current choice: throttle all events to protect system stability
                
                # Acquire semaphore before creating task (prevents unbounded in-flight tasks)
                current_count = event_count[0]
                try:
                    await publish_semaphore.acquire()
                    task = asyncio.create_task(_publish_event_async(redis_client, channel, event, current_count))
                    # Add done callback to release semaphore and log errors
                    # Semaphore is released in callback, not here, to ensure it's always released
                    task.add_done_callback(lambda t, et=event_type, ec=current_count, sem=publish_semaphore: _handle_publish_task_done(t, et, ec, sem))
                    # Note: No need for asyncio.sleep(0) - semaphore already throttles and tasks will execute
                except Exception as e:
                    # If task creation fails, release semaphore
                    try:
                        publish_semaphore.release()
                    except Exception:
                        pass
                    logger.error(f"[REDIS_PUBLISH] Failed to create publish task for {event_type} (event_count={current_count}): {e}", exc_info=True)
            
            # Send heartbeat periodically (every 10 events or on important events)
            if event_count[0] % 10 == 0 or event.get("type") in ["final", "interrupt", "error"]:
                activity.heartbeat({
                    "status": "processing",
                    "chat_id": chat_id,
                    "event_count": event_count[0],
                    "last_event_type": event.get("type"),
                })
            
            # Check for interrupt (LangGraph native interrupt pattern)
            if event.get("type") == "interrupt":
                interrupt_data = event.get("data") or event.get("interrupt")
                logger.info(f"[HITL] [INTERRUPT] Workflow interrupted for chat_id={chat_id}, interrupt_data={interrupt_data}")
                activity.heartbeat({"status": "interrupted", "chat_id": chat_id})
                # Publish interrupt event to Redis for frontend
                if redis_client:
                    asyncio.create_task(_publish_event_async(redis_client, channel, event, event_count[0]))
                return {
                    "status": "interrupted",
                    "interrupt": interrupt_data,
                    "run_id": state.get("run_id")  # Include for consistency
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
        
        # Interrupt should have been handled above - if we reach here, workflow completed normally
        
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
