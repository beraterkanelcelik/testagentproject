"""
Utility functions for user account management.
"""
from django.contrib.auth import get_user_model
from asgiref.sync import sync_to_async
from app.core.logging import get_logger

User = get_user_model()
logger = get_logger(__name__)


def increment_user_token_usage(user_id: int, tokens: int) -> None:
    """
    Increment token usage for a user (synchronous version).
    
    This is the centralized function to persist token usage to User.token_usage_count.
    This value is cumulative and never decreases, ensuring accurate all-time token tracking
    even when individual chats or sessions are deleted.
    
    Should be called whenever tokens are used:
    - LLM calls (chat completions)
    - Embedding model calls
    - Any other token-consuming operations
    
    For async contexts, use increment_user_token_usage_async instead.
    
    Args:
        user_id: User ID
        tokens: Number of tokens to add (must be >= 0)
    """
    if tokens <= 0:
        return
    
    try:
        user = User.objects.get(id=user_id)
        user.token_usage_count += tokens
        user.save(update_fields=['token_usage_count'])
        logger.debug(f"Incremented token usage for user {user_id}: +{tokens} tokens (total: {user.token_usage_count})")
    except User.DoesNotExist:
        logger.warning(f"User {user_id} not found when trying to increment token usage")
    except Exception as e:
        logger.error(f"Error incrementing token usage for user {user_id}: {e}", exc_info=True)


async def increment_user_token_usage_async(user_id: int, tokens: int) -> None:
    """
    Increment token usage for a user (async version for use in async contexts).
    
    Args:
        user_id: User ID
        tokens: Number of tokens to add (must be >= 0)
    """
    if tokens <= 0:
        return
    
    try:
        # Wrap Django ORM calls with sync_to_async
        user = await sync_to_async(
            lambda: User.objects.get(id=user_id)
        )()
        user.token_usage_count += tokens
        await sync_to_async(
            lambda: user.save(update_fields=['token_usage_count'])
        )()
        logger.debug(f"Incremented token usage for user {user_id}: +{tokens} tokens (total: {user.token_usage_count})")
    except User.DoesNotExist:
        logger.warning(f"User {user_id} not found when trying to increment token usage")
    except Exception as e:
        logger.error(f"Error incrementing token usage for user {user_id}: {e}", exc_info=True)
