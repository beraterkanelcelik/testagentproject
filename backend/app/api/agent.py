"""
Agent execution endpoints.
"""
import json
import os
import uuid
import asyncio
from django.http import JsonResponse, StreamingHttpResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from app.core.dependencies import get_current_user, get_current_user_async
from app.agents.runner import execute_agent
from app.core.logging import get_logger
from app.core.redis import get_redis_client
from app.agents.temporal.workflow_manager import get_or_create_workflow
from app.settings import TEMPORAL_ADDRESS, TEMPORAL_TASK_QUEUE

logger = get_logger(__name__)


@csrf_exempt
@require_http_methods(["POST"])
async def run_agent(request):
    """
    Run agent with input message (non-streaming, uses Temporal for durability).
    
    Uses hybrid response: blocks briefly for fast completions, otherwise returns 202 + fetch endpoint.
    
    Request body:
    {
        "chat_session_id": int,
        "message": str
    }
    
    Returns:
    - 200 OK: {"status": "completed", "response": {...}} (fast completion)
    - 202 Accepted: {"status": "approval_required", "interrupt": {...}, "approve_endpoint": "...", "fetch": "..."} (HITL needed)
    - 202 Accepted: {"status": "running", "fetch": "..."} (still running after timeout)
    """
    user = await get_current_user_async(request)
    if not user:
        logger.warning("Unauthenticated request to run_agent endpoint")
        return JsonResponse(
            {'error': 'Authentication required'},
            status=401
        )
    
    try:
        data = json.loads(request.body)
        chat_session_id = data.get('chat_session_id')
        message = data.get('message', '').strip()
        plan_steps = data.get('plan_steps')
        flow = data.get('flow', 'main')
        
        if not chat_session_id:
            logger.warning(f"Missing chat_session_id in run_agent request from user {user.id}")
            return JsonResponse(
                {'error': 'chat_session_id is required'},
                status=400
            )
        
        # For plan execution, message can be empty
        if flow != 'plan' and not message:
            logger.warning(f"Empty message in run_agent request from user {user.id}")
            return JsonResponse(
                {'error': 'message is required'},
                status=400
            )
        
        # Generate run ID for correlation (ensures /run polling returns correct message under concurrency)
        run_id = str(uuid.uuid4())
        logger.info(f"Running agent (non-stream) for user {user.id}, session {chat_session_id}, run_id {run_id}, flow: {flow}")
        
        # Save user message first (only if not plan execution)
        user_message_id = None
        if flow != 'plan' and message:
            from app.services.chat_service import add_message
            from asgiref.sync import sync_to_async
            try:
                user_message = await sync_to_async(add_message)(chat_session_id, 'user', message)
                user_message_id = user_message.id
                logger.debug(f"Saved user message {user_message_id} before agent execution")
            except Exception as e:
                logger.error(f"Error saving user message: {e}", exc_info=True)
                return JsonResponse({'error': 'Failed to save user message'}, status=500)
        
        # Use Temporal workflow for non-stream execution (durable, supports HITL)
        try:
            # Prepare initial state for workflow
            tenant_id = str(user.id)  # Use user_id as tenant_id
            workflow_state = {
                "user_id": user.id,
                "session_id": chat_session_id,
                "message": message,
                "plan_steps": plan_steps,
                "flow": flow,
                "tenant_id": tenant_id,
                "run_id": run_id,  # Correlation ID for /run polling
                "parent_message_id": user_message_id,  # Parent message ID for correlation
                "org_slug": None,  # Not available in current implementation
                "org_roles": [],  # Not available in current implementation
                "app_roles": [],  # Not available in current implementation
            }
            
            # Get or create workflow with mode="non_stream"
            workflow_handle = await get_or_create_workflow(
                user.id,
                chat_session_id,
                initial_state=workflow_state,
                mode="non_stream"
            )
            logger.info(f"Using Temporal workflow {workflow_handle.id} for non-stream chat {chat_session_id}")
            
            # Poll workflow query for activity result (fast, in-memory, strongly consistent)
            # Workflow query returns activity result without waiting for workflow completion
            WAIT_TIMEOUT_SECONDS = int(os.getenv('RUN_AGENT_WAIT_TIMEOUT', '8'))
            POLL_INTERVAL_SECONDS = 0.5  # Check query every 500ms
            max_polls = int(WAIT_TIMEOUT_SECONDS / POLL_INTERVAL_SECONDS)
            
            fetch_endpoint = f"/api/chats/{chat_session_id}/messages/"
            approve_endpoint = "/api/agent/approve-tool/"
            
            import time
            
            # Poll via workflow query (not DB, not workflow.result())
            # Query is fast (in-memory), strongly consistent, and correlated by run_id
            for _ in range(max_polls):
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
                
                try:
                    # Import ChatWorkflow to access query method
                    from app.agents.temporal.workflow import ChatWorkflow
                    last_result = await workflow_handle.query(ChatWorkflow.get_last_result)
                except Exception as e:
                    logger.debug(f"Query failed: {e}")
                    continue
                
                # Check if this result is for our request (correlation by run_id)
                if last_result and last_result.get("run_id") == run_id:
                    # Verify result is recent (avoid stale results from previous requests)
                    result_age = time.time() - last_result.get("timestamp", 0)
                    if result_age > WAIT_TIMEOUT_SECONDS + 5:  # Allow small buffer
                        logger.warning(f"Stale result detected: age={result_age}s, run_id={run_id}")
                        continue  # Keep polling
                    
                    status = last_result.get("status")
                    
                    if status == "completed":
                        return JsonResponse({
                            "status": "completed",
                            "response": last_result["response"]
                        })
                    elif status == "interrupted":
                        return JsonResponse({
                            "status": "approval_required",
                            "interrupt": last_result["interrupt"],
                            "approve_endpoint": approve_endpoint,
                            "fetch": fetch_endpoint
                        }, status=202)
                    elif status == "error":
                        return JsonResponse({
                            "error": last_result.get("error", "Unknown error")
                        }, status=500)
            
            # Timeout - still running
            return JsonResponse({
                "status": "running",
                "fetch": fetch_endpoint,
                "message": "Request still processing. Fetch from DB endpoint to get results when ready."
            }, status=202)
            
        except Exception as e:
            logger.error(f"Error in non-stream execution for user {user.id}, session {chat_session_id}: {e}", exc_info=True)
            return JsonResponse({'error': str(e)}, status=500)
    
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in run_agent request: {e}")
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Unexpected error in run_agent endpoint: {e}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
async def stream_agent(request):
    """
    Stream agent response using SSE (Server-Sent Events).
    
    Request body:
    {
        "chat_session_id": int,
        "message": str
    }
    
    Returns:
    SSE stream with events: token, agent_start, tool_call, error, done
    """
    user = await get_current_user_async(request)
    if not user:
        logger.warning("Unauthenticated request to stream_agent endpoint")
        return JsonResponse(
            {'error': 'Authentication required'},
            status=401
        )
    
    try:
        data = json.loads(request.body)
        chat_session_id = data.get('chat_session_id')
        message = data.get('message', '').strip()
        plan_steps = data.get('plan_steps')
        flow = data.get('flow', 'main')
        
        if not chat_session_id:
            logger.warning(f"Missing chat_session_id in stream_agent request from user {user.id}")
            return JsonResponse(
                {'error': 'chat_session_id is required'},
                status=400
            )
        
        # For plan execution, message can be empty
        if flow != 'plan' and not message:
            logger.warning(f"Empty message in stream_agent request from user {user.id}")
            return JsonResponse(
                {'error': 'message is required'},
                status=400
            )
        
        logger.info(f"Starting agent stream for user {user.id}, session {chat_session_id}, flow: {flow}")
        
        # Save user message first (only if not plan execution)
        user_message_id = None
        if flow != 'plan' and message:
            from app.services.chat_service import add_message
            from asgiref.sync import sync_to_async
            try:
                user_message = await sync_to_async(add_message)(chat_session_id, 'user', message)
                user_message_id = user_message.id
                logger.info(f"[MESSAGE_SAVE] Saved user message ID={user_message.id} session={chat_session_id} content_preview={message[:50]}...")
            except Exception as e:
                logger.error(f"Error saving user message: {e}", exc_info=True)
                return JsonResponse({'error': 'Failed to save user message'}, status=500)
        
        async def event_stream():
            """
            Async generator for SSE events via Redis or direct streaming.
            
            IMPORTANT: Cancellation Behavior
            - SSE disconnect only cancels Redis subscription loop
            - Temporal workflow/activity continues running
            - Results are persisted to DB and can be fetched later
            - This is intentional for durability (work continues even if client disconnects)
            - Execution continues on disconnect for both stream and non-stream modes
            - Non-stream clients should rely on DB fetch/poll
            """
            pubsub = None
            channel = None
            try:
                # Try Redis streaming first (if Temporal is configured)
                use_redis = TEMPORAL_ADDRESS and TEMPORAL_TASK_QUEUE
                
                if use_redis:
                    try:
                        # Get Redis client in this async context (will use current event loop)
                        redis_client = await get_redis_client()
                        tenant_id = str(user.id)  # Use user_id as tenant_id
                        channel = f"chat:{tenant_id}:{chat_session_id}"
                        
                        # Create pubsub instance for this subscription
                        pubsub = redis_client.pubsub()
                        await pubsub.subscribe(channel)
                        
                        # Wait for subscription confirmation
                        # First message is always subscription confirmation
                        confirm_msg = await pubsub.get_message(timeout=5.0)
                        if confirm_msg and confirm_msg['type'] == 'subscribe':
                            logger.info(f"Subscribed to Redis channel: {channel}")
                        else:
                            logger.warning(f"Unexpected subscription confirmation: {confirm_msg}")
                        
                        # Emit message_saved event for user message if saved
                        if user_message_id is not None:
                            try:
                                message_saved_event = {
                                    "type": "message_saved",
                                    "data": {
                                        "role": "user",
                                        "db_id": user_message_id,
                                        "session_id": chat_session_id,
                                    }
                                }
                                event_json = json.dumps(message_saved_event)
                                await redis_client.publish(channel, event_json.encode('utf-8'))
                                logger.info(f"[MESSAGE_SAVED_EVENT] Emitted user message_saved event db_id={user_message_id} session={chat_session_id}")
                            except Exception as e:
                                logger.warning(f"Failed to emit message_saved event for user message: {e}")
                        
                        # Get or create workflow and send message signal
                        try:
                            # Prepare initial state for workflow
                            workflow_state = {
                                "user_id": user.id,
                                "session_id": chat_session_id,
                                "message": message,
                                "plan_steps": plan_steps,
                                "flow": flow,
                                "tenant_id": tenant_id,
                                "parent_message_id": user_message_id,  # Pass parent_message_id for stable dedupe (even in stream mode)
                                "org_slug": None,  # Not available in current implementation
                                "org_roles": [],  # Not available in current implementation
                                "app_roles": [],  # Not available in current implementation
                            }
                            
                            # Get or create workflow with mode="stream" - it will handle signaling automatically
                            # Pass parent_message_id for stable dedupe (prevents same message via /stream then /run from being deduped)
                            workflow_handle = await get_or_create_workflow(
                                user.id,
                                chat_session_id,
                                initial_state=workflow_state,
                                mode="stream"
                            )
                            logger.info(f"Using Temporal workflow {workflow_handle.id} for chat {chat_session_id} (signal sent automatically)")
                        except Exception as e:
                            logger.warning(f"Failed to start Temporal workflow, falling back to direct streaming: {e}", exc_info=True)
                            # Fall back to direct streaming
                            from app.agents.runner import stream_agent_events_async
                            async for event in stream_agent_events_async(
                                user.id, chat_session_id, message, plan_steps, flow
                            ):
                                yield _format_sse_event(event)
                            return
                        
                        # Listen to Redis messages with timeout handling and reconnection
                        # Scalability: Use shorter timeout for approval waiting (5 min) vs normal streaming (10 min)
                        # This prevents long-lived connections from consuming server resources
                        timeout_seconds = 600  # 10 minutes max for normal streaming
                        interrupt_wait_timeout = 300  # 5 minutes max when waiting for interrupt resume
                        loop = asyncio.get_running_loop()
                        start_time = loop.time()
                        waiting_for_resume = False
                        last_heartbeat_time = start_time
                        heartbeat_interval = 30  # Send heartbeat every 30 seconds to keep connection alive
                        
                        # Redis reconnection settings
                        MAX_RECONNECT_ATTEMPTS = 3
                        RECONNECT_DELAY = 1.0
                        reconnect_attempt = 0
                        
                        try:
                            # Reconnection loop with exponential backoff
                            while reconnect_attempt < MAX_RECONNECT_ATTEMPTS:
                                try:
                                    # Subscribe if not already subscribed (first attempt or after reconnect)
                                    if reconnect_attempt > 0:
                                        logger.info(f"Reconnecting to Redis channel {channel} (attempt {reconnect_attempt}/{MAX_RECONNECT_ATTEMPTS})")
                                        pubsub = redis_client.pubsub()
                                        await pubsub.subscribe(channel)
                                        
                                        # Wait for subscription confirmation
                                        confirm_msg = await pubsub.get_message(timeout=5.0)
                                        if confirm_msg and confirm_msg['type'] == 'subscribe':
                                            logger.info(f"Reconnected to Redis channel: {channel}")
                                        else:
                                            logger.warning(f"Unexpected subscription confirmation after reconnect: {confirm_msg}")
                                    
                                    # Reset reconnect attempt on successful connection
                                    reconnect_attempt = 0
                                    
                                    # Listen to messages
                                    async for msg in pubsub.listen():
                                        current_time = loop.time()
                                        elapsed = current_time - start_time
                                        
                                        # Check timeout based on whether we're waiting for interrupt resume
                                        max_timeout = interrupt_wait_timeout if waiting_for_resume else timeout_seconds
                                        if elapsed > max_timeout:
                                            logger.warning(f"Redis subscription timeout after {max_timeout}s for channel {channel} (waiting_for_resume={waiting_for_resume})")
                                            yield _format_sse_event({"type": "error", "data": {"error": f"Subscription timeout after {max_timeout}s"}})
                                            break
                                        
                                        # Send heartbeat to keep connection alive (prevents idle timeouts)
                                        # This is a scalability best practice for long-lived SSE connections
                                        if current_time - last_heartbeat_time >= heartbeat_interval:
                                            try:
                                                yield _format_sse_event({"type": "heartbeat", "data": {"timestamp": current_time}})
                                                last_heartbeat_time = current_time
                                            except Exception as e:
                                                logger.debug(f"Failed to send heartbeat: {e}")
                                        
                                        # Filter subscription confirmation messages
                                        if msg['type'] == 'subscribe' or msg['type'] == 'psubscribe':
                                            continue
                                        
                                        # Process actual messages
                                        if msg['type'] == 'message':
                                            try:
                                                event_data = json.loads(msg['data'].decode('utf-8'))
                                                yield _format_sse_event(event_data)
                                                event_type = event_data.get("type")
                                                
                                                # Track if we're waiting for interrupt resume (affects timeout)
                                                if event_type == "interrupt":
                                                    waiting_for_resume = True
                                                    logger.info(f"[HITL] [SSE] Received interrupt event, connection will timeout after {interrupt_wait_timeout}s if no resume session={chat_session_id}")
                                                    # Don't break - keep connection open but with shorter timeout
                                                    # This balances scalability (timeout) with UX (no reconnection needed)
                                                    continue
                                                elif event_type in ["final", "error", "done"]:
                                                    # Close connection on final/error/done
                                                    break
                                            except json.JSONDecodeError as e:
                                                logger.warning(f"Failed to decode Redis message: {e}")
                                                continue
                                            except Exception as e:
                                                logger.error(f"Error processing Redis message: {e}", exc_info=True)
                                                continue
                                        elif msg['type'] == 'unsubscribe' or msg['type'] == 'punsubscribe':
                                            # Unsubscribed, exit loop
                                            logger.debug(f"Unsubscribed from channel: {channel}")
                                            break
                                    
                                    # If we break from the listen loop normally (not due to error), exit reconnection loop
                                    break
                                    
                                except Exception as e:
                                    # Handle connection errors - check if reconnection is warranted
                                    error_str = str(e).lower()
                                    is_connection_error = any(
                                        phrase in error_str 
                                        for phrase in ['connection', 'disconnected', 'broken pipe', 'timeout']
                                    )
                                    
                                    if is_connection_error and reconnect_attempt < MAX_RECONNECT_ATTEMPTS:
                                        reconnect_attempt += 1
                                        delay = RECONNECT_DELAY * (2 ** (reconnect_attempt - 1))  # Exponential backoff
                                        logger.warning(f"Redis connection error, reconnecting in {delay}s (attempt {reconnect_attempt}/{MAX_RECONNECT_ATTEMPTS}): {e}")
                                        await asyncio.sleep(delay)
                                        continue  # Continue outer loop to reconnect
                                    else:
                                        # Not a connection error or max attempts reached, re-raise
                                        raise
                                        
                        except asyncio.CancelledError:
                            logger.info(f"Redis subscription cancelled for channel {channel}")
                            raise
                        except Exception as e:
                            # Final exception handling - if we've exhausted reconnection attempts
                            if reconnect_attempt >= MAX_RECONNECT_ATTEMPTS:
                                logger.error(f"Redis subscription failed after {MAX_RECONNECT_ATTEMPTS} reconnection attempts: {e}", exc_info=True)
                            else:
                                logger.error(f"Error in Redis subscription loop: {e}", exc_info=True)
                            
                            # Stream failure recovery: best-effort fetch from DB (non-blocking)
                            fetch_endpoint = f"/api/chats/{chat_session_id}/messages/"
                            try:
                                # Best-effort: try to get latest assistant message (non-blocking, don't wait/poll)
                                from app.db.models.message import Message
                                from asgiref.sync import sync_to_async
                                
                                latest_assistant_msg = await sync_to_async(
                                    lambda: Message.objects.filter(
                                        session_id=chat_session_id,
                                        role="assistant"
                                    ).order_by('-created_at').first()
                                )()
                                
                                if latest_assistant_msg:
                                    # Found message - emit recovery event
                                    yield _format_sse_event({
                                        "type": "recovery",
                                        "data": {
                                            "message_id": latest_assistant_msg.id,
                                            "content": latest_assistant_msg.content or "",
                                            "fetch": fetch_endpoint,
                                            "suggestion": "Stream failed, fetched from DB"
                                        }
                                    })
                                else:
                                    # No message found - emit error with fetch endpoint
                                    yield _format_sse_event({
                                        "type": "error",
                                        "data": {
                                            "error": "Stream failed",
                                            "fetch": fetch_endpoint,
                                            "recovery": "Fetch from DB endpoint to get latest"
                                        }
                                    })
                            except Exception as recovery_error:
                                # Recovery fetch failed - still emit error with fetch endpoint
                                logger.debug(f"Recovery fetch failed: {recovery_error}")
                                yield _format_sse_event({
                                    "type": "error",
                                    "data": {
                                        "error": "Stream failed",
                                        "fetch": fetch_endpoint,
                                        "recovery": "Fetch from DB endpoint to get latest"
                                    }
                                })
                            # Exit generator after emitting recovery/error events
                            return
                    except Exception as redis_error:
                        logger.warning(f"Redis streaming failed, falling back to direct: {redis_error}", exc_info=True)
                        
                        # Stream failure recovery: best-effort fetch from DB before falling back
                        fetch_endpoint = f"/api/chats/{chat_session_id}/messages/"
                        try:
                            from app.db.models.message import Message
                            from asgiref.sync import sync_to_async
                            
                            latest_assistant_msg = await sync_to_async(
                                lambda: Message.objects.filter(
                                    session_id=chat_session_id,
                                    role="assistant"
                                ).order_by('-created_at').first()
                            )()
                            
                            if latest_assistant_msg:
                                yield _format_sse_event({
                                    "type": "recovery",
                                    "data": {
                                        "message_id": latest_assistant_msg.id,
                                        "content": latest_assistant_msg.content or "",
                                        "fetch": fetch_endpoint,
                                        "suggestion": "Stream failed, fetched from DB"
                                    }
                                })
                            else:
                                yield _format_sse_event({
                                    "type": "error",
                                    "data": {
                                        "error": "Stream failed",
                                        "fetch": fetch_endpoint,
                                        "recovery": "Fetch from DB endpoint to get latest"
                                    }
                                })
                        except Exception:
                            # Ignore recovery errors - will fall through to direct streaming
                            pass
                        
                        # Fall through to direct streaming
                        use_redis = False
                
                if not use_redis:
                    # Fallback to direct streaming
                    from app.agents.runner import stream_agent_events_async
                    async for event in stream_agent_events_async(
                        user.id, chat_session_id, message, plan_steps, flow
                    ):
                        yield _format_sse_event(event)
                        
            except Exception as e:
                logger.error(f"Error in agent stream for user {user.id}, session {chat_session_id}: {e}", exc_info=True)
                # Send error event
                yield _format_sse_event({
                    "type": "error",
                    "data": {"error": str(e)}
                })
            finally:
                # Cleanup pubsub only if we're still in the same loop that created it
                # CRITICAL: Never create a new loop for cleanup - only cleanup if we're in the same loop
                if pubsub:
                    try:
                        loop = asyncio.get_running_loop()
                        if not loop.is_closed():
                            try:
                                await pubsub.unsubscribe()
                                await pubsub.punsubscribe()
                                await pubsub.close()
                                logger.debug(f"Cleaned up Redis pubsub for channel {channel or 'unknown'}")
                            except (RuntimeError, asyncio.CancelledError) as e:
                                logger.debug(f"Event loop closing, skipping pubsub cleanup: {e}")
                        else:
                            logger.debug("Event loop is closed, skipping pubsub cleanup")
                    except RuntimeError:
                        # No running loop - skip cleanup (non-critical)
                        # This is safe: pubsub will be cleaned up when the process exits
                        logger.debug("No running event loop for pubsub cleanup, skipping (non-critical)")
                    except Exception as e:
                        logger.debug(f"Error cleaning up Redis pubsub (non-critical): {e}")
        
        def _format_sse_event(event: dict) -> str:
            """Format event dict as SSE data line."""
            if isinstance(event, dict):
                event_type = event.get("type")
                
                # Transform token events: "value" -> "data"
                if event_type == "token" and "value" in event and "data" not in event:
                    event["data"] = event.pop("value")
                
                # Transform final events to done events for frontend compatibility
                elif event_type == "final":
                    if "response" in event:
                        response = event["response"]
                        # Serialize AgentResponse if needed
                        if hasattr(response, 'model_dump'):  # Pydantic v2
                            response = response.model_dump()
                        elif hasattr(response, 'dict'):  # Pydantic v1
                            response = response.dict()
                        
                        # Format as done event with data
                        if isinstance(response, dict):
                            event["type"] = "done"
                            event["data"] = {
                                "tokens_used": response.get("token_usage", {}).get("total_tokens", 0),
                                "raw_tool_outputs": response.get("raw_tool_outputs"),
                                "agent": response.get("agent_name"),
                                "tool_calls": response.get("tool_calls", []),
                            }
                            # Remove response field as it's now in data
                            event.pop("response", None)
                        else:
                            event["data"] = response
                
                # Ensure AgentResponse objects are serialized for other event types
                elif "response" in event:
                    response = event["response"]
                    if hasattr(response, 'model_dump'):  # Pydantic v2
                        event["response"] = response.model_dump()
                    elif hasattr(response, 'dict'):  # Pydantic v1
                        event["response"] = response.dict()
            
            return f"data: {json.dumps(event, default=str)}\n\n"
        
        # Emit initial event with metadata about disconnect behavior
        # Note: This will be the first event in the stream
        async def event_stream_with_metadata():
            # Yield initial metadata event
            yield _format_sse_event({
                "type": "stream_start",
                "metadata": {
                    "continues_on_disconnect": True,
                    "fetch": f"/api/chats/{chat_session_id}/messages/"
                }
            })
            # Then yield all other events
            async for event in event_stream():
                yield event
        
        # Django 5.0+ supports async generators directly with StreamingHttpResponse
        # No need for sync wrapper or new event loops - everything runs in the same async context
        response = StreamingHttpResponse(
            event_stream_with_metadata(),
            content_type='text/event-stream'
        )
        response['Cache-Control'] = 'no-cache'
        response['X-Accel-Buffering'] = 'no'
        # Document cancellation behavior in header
        response['X-Execution-Continues-On-Disconnect'] = 'true'
        return response
    
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in stream_agent request: {e}")
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Unexpected error in stream_agent endpoint: {e}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
async def approve_tool(request):
    """
    Resume interrupted workflow with approval decisions (LangGraph native interrupt pattern).
    
    Request body:
    {
        "chat_session_id": int,
        "resume": {
            "approvals": {
                "tool_call_id": {
                    "approved": bool,
                    "args": dict  # Optional edited args
                }
            }
        }
    }
    
    Returns:
    {
        "success": bool,
        "error": str (if failed)
    }
    """
    user = await get_current_user_async(request)
    if not user:
        logger.warning("Unauthenticated request to approve_tool endpoint")
        return JsonResponse(
            {'error': 'Authentication required'},
            status=401
        )
    
    try:
        data = json.loads(request.body)
        chat_session_id = data.get('chat_session_id')
        resume = data.get('resume')
        
        if not chat_session_id:
            logger.warning(f"Missing chat_session_id in approve_tool request from user {user.id}")
            return JsonResponse(
                {'error': 'chat_session_id is required'},
                status=400
            )
        
        if not resume:
            logger.warning(f"Missing resume in approve_tool request from user {user.id}")
            return JsonResponse(
                {'error': 'resume is required'},
                status=400
            )
        
        logger.info(f"[HITL] [RESUME] Resume request received: user={user.id} session={chat_session_id} resume_keys={list(resume.keys()) if isinstance(resume, dict) else 'N/A'}")
        
        # Send resume signal to Temporal workflow (human-in-the-loop integration)
        try:
            from app.agents.temporal.workflow_manager import get_or_create_workflow
            workflow_handle = await get_or_create_workflow(user.id, chat_session_id)
            
            # Send resume signal with resume_payload
            await workflow_handle.signal(
                "resume",
                args=(resume,)
            )
            logger.info(f"[HITL] [RESUME] Sent resume signal to workflow: session={chat_session_id}")
        except Exception as e:
            logger.error(f"[HITL] [RESUME] Failed to send resume signal to workflow: error={e} session={chat_session_id}", exc_info=True)
            return JsonResponse({
                'success': False,
                'error': f'Failed to send resume signal: {str(e)}'
            }, status=500)
        
        # Block and wait for final response (non-streaming mode: wait for completion)
        # This eliminates the need for frontend polling
        from app.db.models.message import Message
        from asgiref.sync import sync_to_async
        import time
        
        WAIT_TIMEOUT_SECONDS = int(os.getenv('APPROVE_TOOL_WAIT_TIMEOUT', '30'))  # Longer timeout for tool execution
        POLL_INTERVAL_SECONDS = 0.5
        
        # Get the user message ID that triggered this approval (for correlation)
        # Find the most recent user message in this session
        user_message = await sync_to_async(
            lambda: Message.objects.filter(
                session_id=chat_session_id,
                role="user"
            ).order_by('-created_at').first()
        )()
        
        user_message_id = user_message.id if user_message else None
        
        start_time = time.time()
        
        # Poll for final assistant message (after tool execution completes)
        while (time.time() - start_time) < WAIT_TIMEOUT_SECONDS:
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            
            try:
                # Find assistant message created after the user message (final response)
                latest_assistant_msg = await sync_to_async(
                    lambda: Message.objects.filter(
                        session_id=chat_session_id,
                        role="assistant"
                    ).order_by('-created_at').first()
                )()
                
                # Check if this is a new message (after the user message that triggered approval)
                if latest_assistant_msg and user_message_id:
                    # Check if this assistant message was created after the user message
                    if latest_assistant_msg.id > user_message_id or latest_assistant_msg.created_at > user_message.created_at:
                        # Check if it has content (final response, not just tool calls)
                        metadata = latest_assistant_msg.metadata or {}
                        tool_calls = metadata.get("tool_calls", [])
                        has_content = latest_assistant_msg.content and latest_assistant_msg.content.strip()
                        
                        # If it has content, it's the final response
                        if has_content:
                            # Return final response directly (no polling needed in frontend)
                            return JsonResponse({
                                'success': True,
                                'response': {
                                    'reply': latest_assistant_msg.content or "",
                                    'agent_name': metadata.get("agent_name", "assistant"),
                                    'tool_calls': tool_calls,
                                }
                            })
                elif latest_assistant_msg:
                    # Fallback: if we can't correlate, check if message has content
                    metadata = latest_assistant_msg.metadata or {}
                    if latest_assistant_msg.content and latest_assistant_msg.content.strip():
                        return JsonResponse({
                            'success': True,
                            'response': {
                                'reply': latest_assistant_msg.content or "",
                                'agent_name': metadata.get("agent_name", "assistant"),
                                'tool_calls': metadata.get("tool_calls", []),
                            }
                        })
                        
            except Exception as e:
                logger.debug(f"Error polling DB for final response after approval: {e}")
                continue
        
        # Timeout - workflow might still be processing
        logger.warning(f"[HITL] [RESUME] Timeout waiting for final response after approval: session={chat_session_id}")
        return JsonResponse({
            'success': True,
            'status': 'processing',
            'message': 'Tool approved and executing. Response will be available shortly.',
            'fetch': f"/api/chats/{chat_session_id}/messages/"
        })
    
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in approve_tool request: {e}")
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Unexpected error in approve_tool endpoint: {e}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)
