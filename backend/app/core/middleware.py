"""
Middleware for request-level concurrency limiting and other cross-cutting concerns.
"""
import asyncio
import os
from typing import Callable
from django.http import HttpRequest, HttpResponse, JsonResponse
from app.core.logging import get_logger

logger = get_logger(__name__)

# Global semaphore for request-level concurrency limiting
# Prevents unbounded concurrent requests from overwhelming the system
REQUEST_SEMAPHORE = asyncio.Semaphore(int(os.getenv('MAX_CONCURRENT_REQUESTS', '100')))


def concurrency_middleware(get_response: Callable) -> Callable:
    """
    Middleware to limit concurrent requests using a semaphore.
    
    This prevents unbounded concurrent requests from overwhelming the system,
    especially during high load or DDoS scenarios.
    
    Usage in settings.py:
        MIDDLEWARE = [
            ...
            'app.core.middleware.concurrency_middleware',
            ...
        ]
    
    Args:
        get_response: Django's get_response callable (async in ASGI apps)
        
    Returns:
        Async middleware function
    """
    async def middleware(request: HttpRequest) -> HttpResponse:
        try:
            async with REQUEST_SEMAPHORE:
                response = await get_response(request)
                return response
        except asyncio.TimeoutError:
            logger.warning(f"Request concurrency limit reached, rejecting request: {request.path}")
            return JsonResponse(
                {"error": "Server is busy, please try again later"},
                status=503
            )
        except Exception as e:
            logger.error(f"Error in concurrency middleware: {e}", exc_info=True)
            # Don't block the request if middleware fails
            return await get_response(request)
    
    return middleware
