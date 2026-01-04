"""
Chat session and message endpoints.
"""
import json
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from app.core.dependencies import get_current_user
from app.services.chat_service import (
    create_session,
    get_user_sessions,
    get_session,
    delete_session,
    add_message,
    get_messages,
    get_session_stats,
)


@csrf_exempt
@require_http_methods(["GET", "POST"])
def chat_sessions(request):
    """List or create chat sessions."""
    user = get_current_user(request)
    if not user:
        return JsonResponse(
            {'error': 'Authentication required'},
            status=401
        )
    
    if request.method == 'GET':
        # List user's chat sessions
        sessions = get_user_sessions(user.id)
        sessions_data = [
            {
                'id': session.id,
                'title': session.title,
                'tokens_used': session.tokens_used,
                'created_at': session.created_at.isoformat(),
                'updated_at': session.updated_at.isoformat(),
            }
            for session in sessions
        ]
        return JsonResponse({'sessions': sessions_data})
    
    elif request.method == 'POST':
        # Create new chat session
        try:
            data = json.loads(request.body) if request.body else {}
            title = data.get('title', None)
            session = create_session(user.id, title)
            return JsonResponse({
                'id': session.id,
                'title': session.title,
                'created_at': session.created_at.isoformat(),
            }, status=201)
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["GET", "DELETE"])
def chat_session_detail(request, session_id):
    """Get or delete specific chat session."""
    user = get_current_user(request)
    if not user:
        return JsonResponse(
            {'error': 'Authentication required'},
            status=401
        )
    
    if request.method == 'GET':
        # Get chat session details
        session = get_session(user.id, session_id)
        if not session:
            return JsonResponse(
                {'error': 'Chat session not found'},
                status=404
            )
        
        return JsonResponse({
            'id': session.id,
            'title': session.title,
            'tokens_used': session.tokens_used,
            'model_used': session.model_used,
            'created_at': session.created_at.isoformat(),
            'updated_at': session.updated_at.isoformat(),
        })
    
    elif request.method == 'DELETE':
        # Delete chat session
        success = delete_session(user.id, session_id)
        if not success:
            return JsonResponse(
                {'error': 'Chat session not found'},
                status=404
            )
        return JsonResponse({'message': 'Chat session deleted successfully'})


@csrf_exempt
@require_http_methods(["GET", "POST"])
def chat_messages(request, session_id):
    """Get or send messages in a chat session."""
    user = get_current_user(request)
    if not user:
        return JsonResponse(
            {'error': 'Authentication required'},
            status=401
        )
    
    # Verify session belongs to user
    session = get_session(user.id, session_id)
    if not session:
        return JsonResponse(
            {'error': 'Chat session not found'},
            status=404
        )
    
    if request.method == 'GET':
        # Get messages in session
        messages = get_messages(session_id)
        messages_data = [
            {
                'id': msg.id,
                'role': msg.role,
                'content': msg.content,
                'tokens_used': msg.tokens_used,
                'created_at': msg.created_at.isoformat(),
                'metadata': msg.metadata or {},
            }
            for msg in messages
        ]
        return JsonResponse({'messages': messages_data})
    
    elif request.method == 'POST':
        # Send message and get agent response
        try:
            data = json.loads(request.body)
            content = data.get('content', '').strip()
            
            if not content:
                return JsonResponse(
                    {'error': 'Message content is required'},
                    status=400
                )
            
            # Add user message first
            user_message = add_message(session_id, 'user', content, tokens_used=0)
            
            # Execute agent (nodes will save assistant message with tokens)
            from app.agents.runner import execute_agent
            
            result = execute_agent(
                user_id=user.id,
                chat_session_id=session_id,
                message=content
            )
            
            # Get the assistant message that was saved by the node
            from app.db.models.message import Message
            assistant_messages = Message.objects.filter(
                session_id=session_id,
                role='assistant'
            ).order_by('-created_at')[:1]
            
            assistant_message = assistant_messages[0] if assistant_messages else None
            
            return JsonResponse({
                'message': 'Message sent successfully',
                'user_message': {
                    'id': user_message.id,
                    'role': user_message.role,
                    'content': user_message.content,
                    'created_at': user_message.created_at.isoformat(),
                },
                'assistant_message': {
                    'id': assistant_message.id if assistant_message else None,
                    'role': assistant_message.role if assistant_message else 'assistant',
                    'content': assistant_message.content if assistant_message else result.get("response", ""),
                    'tokens_used': assistant_message.tokens_used if assistant_message else 0,
                    'created_at': assistant_message.created_at.isoformat() if assistant_message else None,
                },
                'agent': result.get("agent"),
                'tool_calls': result.get("tool_calls", []),
            }, status=201)
        
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["GET"])
def chat_session_stats(request, session_id):
    """Get statistics for a chat session."""
    user = get_current_user(request)
    if not user:
        return JsonResponse(
            {'error': 'Authentication required'},
            status=401
        )
    
    # Verify session belongs to user
    session = get_session(user.id, session_id)
    if not session:
        return JsonResponse(
            {'error': 'Chat session not found'},
            status=404
        )
    
    stats = get_session_stats(session_id)
    if not stats:
        return JsonResponse(
            {'error': 'Failed to get session statistics'},
            status=500
        )
    
    return JsonResponse(stats)
