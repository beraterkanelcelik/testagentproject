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


def delete_session(user_id: int, session_id: int) -> bool:
    """
    Delete a chat session.
    
    Args:
        user_id: User ID
        session_id: Session ID
        
    Returns:
        True if deleted, False if not found
    """
    try:
        session = ChatSession.objects.get(id=session_id, user_id=user_id)
        session.delete()
        logger.debug(f"Deleted chat session {session_id} for user {user_id}")
        return True
    except ChatSession.DoesNotExist:
        return False


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
        
        # Update user token usage
        user = session.user
        user.token_usage_count += tokens_used
        user.save(update_fields=['token_usage_count'])
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
    Get statistics for a chat session.
    
    Args:
        session_id: Session ID
        
    Returns:
        Dictionary with session statistics
    """
    try:
        from app.core.pricing import calculate_cost
        
        session = ChatSession.objects.get(id=session_id)
        messages = Message.objects.filter(session_id=session_id)
        
        # Count messages by role
        user_messages = messages.filter(role='user').count()
        assistant_messages = messages.filter(role='assistant').count()
        total_messages = messages.count()
        
        # Calculate token usage breakdown
        total_tokens = session.tokens_used
        message_tokens = sum(msg.tokens_used for msg in messages)
        
        # Aggregate I/O tokens from messages
        total_input_tokens = 0
        total_output_tokens = 0
        total_cached_tokens = 0
        
        for msg in messages:
            metadata = msg.metadata or {}
            total_input_tokens += metadata.get('input_tokens', 0)
            total_output_tokens += metadata.get('output_tokens', 0)
            total_cached_tokens += metadata.get('cached_tokens', 0)
        
        # Calculate cost
        model_name = session.model_used
        cost_info = calculate_cost(
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
            cached_tokens=total_cached_tokens,
            model_name=model_name
        )
        
        # Agent usage statistics
        agent_usage = {}
        tool_usage = {}
        
        for msg in messages.filter(role='assistant'):
            metadata = msg.metadata or {}
            agent_name = metadata.get('agent_name', 'unknown')
            agent_usage[agent_name] = agent_usage.get(agent_name, 0) + 1
            
            # Count tool calls
            tool_calls = metadata.get('tool_calls', [])
            for tool_call in tool_calls:
                tool_name = tool_call.get('tool', 'unknown') if isinstance(tool_call, dict) else 'unknown'
                tool_usage[tool_name] = tool_usage.get(tool_name, 0) + 1
        
        return {
            'session_id': session_id,
            'title': session.title,
            'created_at': session.created_at.isoformat(),
            'updated_at': session.updated_at.isoformat(),
            'total_messages': total_messages,
            'user_messages': user_messages,
            'assistant_messages': assistant_messages,
            'total_tokens': total_tokens,
            'message_tokens': message_tokens,
            'input_tokens': total_input_tokens,
            'output_tokens': total_output_tokens,
            'cached_tokens': total_cached_tokens,
            'model_used': session.model_used,
            'cost': {
                'total': float(cost_info['total_cost']),
                'input': float(cost_info['input_cost']),
                'output': float(cost_info['output_cost']),
                'cached': float(cost_info['cached_cost']),
            },
            'agent_usage': agent_usage,
            'tool_usage': tool_usage,
        }
    except ChatSession.DoesNotExist:
        return None
