"""
Chat service layer for business logic.
"""
from typing import List, Dict, Any, Optional
from app.db.models.session import ChatSession
from app.db.models.message import Message
from app.core.logging import get_logger

logger = get_logger(__name__)


def create_session(user_id: int, title: Optional[str] = None) -> ChatSession:
    """
    Create a new chat session.
    
    Args:
        user_id: User ID
        title: Optional session title
        
    Returns:
        Created ChatSession object
    """
    from django.contrib.auth import get_user_model
    User = get_user_model()
    
    user = User.objects.get(id=user_id)
    session = ChatSession.objects.create(
        user=user,
        title=title,
    )
    logger.debug(f"Created chat session {session.id} for user {user_id}")
    return session


def get_user_sessions(user_id: int) -> List[ChatSession]:
    """
    Get all chat sessions for a user.
    
    Args:
        user_id: User ID
        
    Returns:
        List of ChatSession objects
    """
    return ChatSession.objects.filter(user_id=user_id).order_by('-updated_at')


def get_session(user_id: int, session_id: int) -> Optional[ChatSession]:
    """
    Get a specific chat session.
    
    Args:
        user_id: User ID
        session_id: Session ID
        
    Returns:
        ChatSession object or None if not found
    """
    try:
        return ChatSession.objects.get(id=session_id, user_id=user_id)
    except ChatSession.DoesNotExist:
        return None


def update_session_model(user_id: int, session_id: int, model_name: str) -> Optional[ChatSession]:
    """
    Update the model used for a chat session.
    
    Args:
        user_id: User ID
        session_id: Session ID
        model_name: Model name to set
        
    Returns:
        Updated ChatSession object or None if not found
    """
    try:
        session = ChatSession.objects.get(id=session_id, user_id=user_id)
        session.model_used = model_name
        session.save(update_fields=['model_used', 'updated_at'])
        logger.debug(f"Updated model for session {session_id} to {model_name}")
        return session
    except ChatSession.DoesNotExist:
        return None


def update_session_title(user_id: int, session_id: int, title: str) -> Optional[ChatSession]:
    """
    Update the title of a chat session.
    
    Args:
        user_id: User ID
        session_id: Session ID
        title: New title
        
    Returns:
        Updated ChatSession object or None if not found
    """
    try:
        session = ChatSession.objects.get(id=session_id, user_id=user_id)
        session.title = title
        session.save(update_fields=['title', 'updated_at'])
        logger.debug(f"Updated title for session {session_id} to {title}")
        return session
    except ChatSession.DoesNotExist:
        return None


def delete_session(user_id: int, session_id: int) -> bool:
    """
    Delete a chat session and terminate its Temporal workflow.
    
    Args:
        user_id: User ID
        session_id: Session ID
        
    Returns:
        True if deleted, False if not found
    """
    try:
        session = ChatSession.objects.get(id=session_id, user_id=user_id)
        
        # Terminate Temporal workflow before deleting session
        try:
            from asgiref.sync import async_to_sync
            from app.agents.temporal.workflow_manager import terminate_workflow
            
            # Use async_to_sync instead of creating new event loop
            # This avoids "Future attached to different loop" errors
            async_to_sync(terminate_workflow)(user_id, session_id)
        except Exception as e:
            logger.warning(f"Failed to terminate workflow for session {session_id}: {e}")
            # Continue with deletion even if workflow termination fails
        
        session.delete()
        logger.debug(f"Deleted chat session {session_id} for user {user_id}")
        return True
    except ChatSession.DoesNotExist:
        return False


def delete_all_sessions(user_id: int) -> int:
    """
    Delete all chat sessions for a user and terminate their Temporal workflows.
    
    Args:
        user_id: User ID
        
    Returns:
        Number of sessions deleted
    """
    # Get session IDs before deletion
    session_ids = list(ChatSession.objects.filter(user_id=user_id).values_list('id', flat=True))
    deleted_count = len(session_ids)
    
    # Terminate all workflows for this user
    try:
        from asgiref.sync import async_to_sync
        from app.agents.temporal.workflow_manager import terminate_all_workflows_for_user
        
        # Use async_to_sync instead of creating new event loop
        # This avoids "Future attached to different loop" errors
        async_to_sync(terminate_all_workflows_for_user)(user_id)
    except Exception as e:
        logger.warning(f"Failed to terminate workflows for user {user_id}: {e}")
        # Continue with deletion even if workflow termination fails
    
    # Delete all sessions
    ChatSession.objects.filter(user_id=user_id).delete()
    logger.debug(f"Deleted {deleted_count} chat sessions for user {user_id}")
    return deleted_count


def add_message(session_id, role, content, tokens_used=0, metadata=None):
    """
    Add a message to a chat session.
    Updates session and user token usage if tokens_used > 0.
    
    Returns: Message object
    """
    session = ChatSession.objects.get(id=session_id)
    
    # Create message
    message = Message.objects.create(
        session=session,
        role=role,
        content=content,
        tokens_used=tokens_used,
        metadata=metadata or {}
    )
    
    # Update session token usage and timestamp
    if tokens_used > 0:
        session.tokens_used += tokens_used
        session.save(update_fields=['tokens_used', 'updated_at'])
        
        # Use centralized utility function for token persistence
        from app.account.utils import increment_user_token_usage
        increment_user_token_usage(session.user.id, tokens_used)
    else:
        session.save(update_fields=['updated_at'])
    
    logger.debug(f"Added message to session {session_id}: role={role}, tokens={tokens_used}")
    
    return message


def get_messages(session_id):
    """
    Get all messages for a chat session.
    
    Args:
        session_id: Session ID
        
    Returns:
        QuerySet of Message objects
    """
    return Message.objects.filter(session_id=session_id).order_by('created_at')


def get_session_stats(session_id: int) -> Dict[str, Any]:
    """
    Get statistics for a chat session using Langfuse Metrics API.
    
    Message counts are retrieved from database, while token usage, costs,
    and agent/tool analytics come from Langfuse Metrics API v2.
    
    Args:
        session_id: Session ID
        
    Returns:
        Dictionary with session statistics
        
    Raises:
        ValueError: If Langfuse metrics are unavailable
        ChatSession.DoesNotExist: If session not found
    """
    from app.services.langfuse_metrics import get_session_metrics_from_langfuse
    
    # 1. Get session from database (for metadata)
    session = ChatSession.objects.get(id=session_id)
    
    # 2. Get message counts from database (simpler, more reliable)
    messages = Message.objects.filter(session_id=session_id)
    user_messages = messages.filter(role='user').count()
    assistant_messages = messages.filter(role='assistant').count()
    total_messages = messages.count()
    
    # 3. Query Langfuse Metrics API
    langfuse_metrics = get_session_metrics_from_langfuse(session_id)
    if not langfuse_metrics:
        raise ValueError("Langfuse metrics unavailable. Ensure Langfuse is enabled and session has traces.")
    
    # 4. Combine database + Langfuse data
    return {
        'session_id': session_id,
        'title': session.title,
        'created_at': session.created_at.isoformat(),
        'updated_at': session.updated_at.isoformat(),
        'total_messages': total_messages,
        'user_messages': user_messages,
        'assistant_messages': assistant_messages,
        # From Langfuse Metrics API:
        'total_tokens': langfuse_metrics.get('total_tokens', 0),
        'message_tokens': langfuse_metrics.get('total_tokens', 0),  # Use total_tokens as message_tokens
        'input_tokens': langfuse_metrics.get('input_tokens', 0),
        'output_tokens': langfuse_metrics.get('output_tokens', 0),
        'cached_tokens': langfuse_metrics.get('cached_tokens', 0),
        'model_used': session.model_used,
        'cost': langfuse_metrics.get('cost', {
            'total': 0.0,
            'input': 0.0,
            'output': 0.0,
            'cached': 0.0,
        }),
        'agent_usage': langfuse_metrics.get('agent_usage', {}),
        'tool_usage': langfuse_metrics.get('tool_usage', {}),
        'activity_timeline': langfuse_metrics.get('activity_timeline', []),  # User-friendly activity log
    }
