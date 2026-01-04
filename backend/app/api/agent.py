"""
Agent execution endpoints.
"""
import json
import uuid
from django.http import JsonResponse, StreamingHttpResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from app.core.dependencies import get_current_user
from app.agents.runner import execute_agent, stream_agent_events
from app.core.logging import get_logger

logger = get_logger(__name__)


@csrf_exempt
@require_http_methods(["POST"])
def run_agent(request):
    """
    Run agent with input message.
    
    Request body:
    {
        "chat_session_id": int,
        "message": str
    }
    
    Returns:
    {
        "run_id": str,
        "response": str,
        "agent": str,
        "tool_calls": list
    }
    """
    user = get_current_user(request)
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
        
        if not chat_session_id:
            logger.warning(f"Missing chat_session_id in run_agent request from user {user.id}")
            return JsonResponse(
                {'error': 'chat_session_id is required'},
                status=400
            )
        
        if not message:
            logger.warning(f"Empty message in run_agent request from user {user.id}")
            return JsonResponse(
                {'error': 'message is required'},
                status=400
            )
        
        # Generate run ID
        run_id = str(uuid.uuid4())
        logger.info(f"Running agent for user {user.id}, session {chat_session_id}, run_id {run_id}")
        
        # Execute agent
        result = execute_agent(
            user_id=user.id,
            chat_session_id=chat_session_id,
            message=message
        )
        
        if not result.get("success"):
            logger.error(f"Agent execution failed for user {user.id}, session {chat_session_id}: {result.get('error')}")
            return JsonResponse(
                {'error': result.get("error", "Agent execution failed")},
                status=500
            )
        
        logger.info(f"Agent execution completed successfully for run_id {run_id}")
        return JsonResponse({
            'run_id': run_id,
            'response': result.get("response", ""),
            'agent': result.get("agent"),
            'tool_calls': result.get("tool_calls", []),
        })
    
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in run_agent request: {e}")
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Unexpected error in run_agent endpoint: {e}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def stream_agent(request):
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
    user = get_current_user(request)
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
        
        if not chat_session_id:
            logger.warning(f"Missing chat_session_id in stream_agent request from user {user.id}")
            return JsonResponse(
                {'error': 'chat_session_id is required'},
                status=400
            )
        
        if not message:
            logger.warning(f"Empty message in stream_agent request from user {user.id}")
            return JsonResponse(
                {'error': 'message is required'},
                status=400
            )
        
        logger.info(f"Starting agent stream for user {user.id}, session {chat_session_id}")
        
        # Save user message first
        from app.services.chat_service import add_message
        try:
            user_message = add_message(chat_session_id, 'user', message)
            logger.debug(f"Saved user message {user_message.id} before streaming")
        except Exception as e:
            logger.error(f"Error saving user message: {e}", exc_info=True)
            return JsonResponse({'error': 'Failed to save user message'}, status=500)
        
        def event_stream():
            """Generator for SSE events."""
            try:
                # Stream agent events
                for event in stream_agent_events(
                    user_id=user.id,
                    chat_session_id=chat_session_id,
                    message=message
                ):
                    # Format as SSE
                    yield f"data: {json.dumps(event)}\n\n"
            except Exception as e:
                logger.error(f"Error in agent stream for user {user.id}, session {chat_session_id}: {e}", exc_info=True)
                # Send error event
                error_event = {
                    "type": "error",
                    "data": {"error": str(e)}
                }
                yield f"data: {json.dumps(error_event)}\n\n"
        
        response = StreamingHttpResponse(
            event_stream(),
            content_type='text/event-stream'
        )
        response['Cache-Control'] = 'no-cache'
        response['X-Accel-Buffering'] = 'no'
        return response
    
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in stream_agent request: {e}")
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Unexpected error in stream_agent endpoint: {e}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)
