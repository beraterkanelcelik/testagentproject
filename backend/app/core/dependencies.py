"""
Dependency injection utilities.
"""
from typing import Optional
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken
from asgiref.sync import sync_to_async

User = get_user_model()


def get_current_user(request) -> Optional[User]:
    """
    Get current authenticated user from request (synchronous version).
    Supports both JWT and session authentication.
    """
    # Try JWT authentication first
    jwt_auth = JWTAuthentication()
    try:
        validated_token = jwt_auth.get_validated_token(jwt_auth.get_raw_token(jwt_auth.get_header(request)))
        user = jwt_auth.get_user(validated_token)
        return user
    except (InvalidToken, AttributeError, TypeError):
        pass
    
    # Fall back to session authentication
    if hasattr(request, 'user') and request.user.is_authenticated:
        return request.user
    
    return None


async def get_current_user_async(request) -> Optional[User]:
    """
    Get current authenticated user from request (async version).
    Supports both JWT and session authentication.
    Uses sync_to_async for database operations.
    """
    # Try JWT authentication first
    jwt_auth = JWTAuthentication()
    try:
        # These operations are sync but don't hit the DB
        raw_token = jwt_auth.get_raw_token(jwt_auth.get_header(request))
        validated_token = jwt_auth.get_validated_token(raw_token)
        
        # get_user() does a DB query, so we need to wrap it
        user = await sync_to_async(jwt_auth.get_user)(validated_token)
        return user
    except (InvalidToken, AttributeError, TypeError):
        pass
    
    # Fall back to session authentication
    # request.user access is safe in async context (it's a cached property)
    if hasattr(request, 'user') and request.user.is_authenticated:
        return request.user
    
    return None


def require_auth(request):
    """
    Check if request is authenticated.
    Raises exception if not authenticated.
    """
    user = get_current_user(request)
    if not user:
        from django.http import JsonResponse
        return JsonResponse({'error': 'Authentication required'}, status=401)
    return user
