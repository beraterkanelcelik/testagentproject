"""
Redis integration for pub/sub streaming.
CRITICAL: Redis clients and pools must be created per event loop to avoid "Future attached to different loop" errors.
Best practice: Use per-loop ConnectionPool and per-loop clients, with WeakKeyDictionary to prevent leaks.
"""
import asyncio
import weakref
from urllib.parse import urlparse, urlunparse
from typing import Optional

import redis.asyncio as redis
from app.settings import REDIS_URL, REDIS_PASSWORD
from app.core.logging import get_logger

logger = get_logger(__name__)

# Per-loop pools and clients (automatically cleaned up when loops are garbage collected)
_pools_by_loop: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, redis.ConnectionPool] = weakref.WeakKeyDictionary()
_clients_by_loop: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, redis.Redis] = weakref.WeakKeyDictionary()


def _url_with_password(url: str, password: Optional[str]) -> str:
    """
    Safely inject password into Redis URL using urllib.parse.
    
    Args:
        url: Redis URL (with or without scheme)
        password: Optional password to inject
        
    Returns:
        URL with password injected if password provided and not already present
    """
    if not password:
        return url

    # Parse URL, adding default scheme if missing
    parsed = urlparse(url if "://" in url else f"redis://{url}")
    
    # If auth already present, keep it as-is
    if parsed.password is not None or parsed.username is not None:
        return url

    # Inject password (username empty, password set)
    netloc = f":{password}@{parsed.hostname}"
    if parsed.port:
        netloc += f":{parsed.port}"

    return urlunparse(parsed._replace(netloc=netloc))


async def get_redis_client() -> redis.Redis:
    """
    Get or create Redis async client for the current event loop.
    Uses per-loop ConnectionPool and per-loop clients to ensure loop isolation.
    
    Returns:
        Redis async client instance for current event loop
        
    Raises:
        RuntimeError: If called without a running event loop
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        raise RuntimeError("get_redis_client() must be called from an async context with a running loop")

    # Check if we already have a client for this loop
    client = _clients_by_loop.get(loop)
    if client is not None:
        return client

    # Create per-loop pool if needed
    pool = _pools_by_loop.get(loop)
    if pool is None:
        url = _url_with_password(REDIS_URL, REDIS_PASSWORD)
        pool = redis.ConnectionPool.from_url(
            url,
            decode_responses=False,  # We'll decode in the caller
            socket_connect_timeout=5,
            socket_timeout=5,
            max_connections=50,
            retry_on_timeout=True,
        )
        _pools_by_loop[loop] = pool
        logger.info("Redis connection pool created for loop %s", id(loop))

    # Create new client for this event loop using the per-loop pool
    client = redis.Redis(connection_pool=pool)
    _clients_by_loop[loop] = client
    logger.info("Redis client created for loop %s", id(loop))
    
    return client


async def close_redis_for_current_loop() -> None:
    """
    Close Redis client and pool for the current event loop.
    CRITICAL: Must be called from within the same loop that created the client/pool.
    
    This is useful for explicit cleanup, but WeakKeyDictionary will automatically
    clean up when loops are garbage collected.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("close_redis_for_current_loop() called without a running loop - skipping")
        return

    # Close client if it exists
    client = _clients_by_loop.pop(loop, None)
    if client is not None:
        try:
            # Try aclose() first (newer redis-py versions)
            if hasattr(client, 'aclose'):
                await client.aclose()
            else:
                await client.close()
            logger.info("Redis client closed for loop %s", id(loop))
        except Exception as e:
            logger.error(f"Error closing Redis client for loop {id(loop)}: {e}", exc_info=True)

    # Disconnect pool if it exists
    pool = _pools_by_loop.pop(loop, None)
    if pool is not None:
        try:
            # Try async disconnect first
            if hasattr(pool, 'disconnect') and asyncio.iscoroutinefunction(pool.disconnect):
                await pool.disconnect(inuse_connections=True)
            else:
                # Fallback for sync disconnect
                pool.disconnect(inuse_connections=True)
            logger.info("Redis pool disconnected for loop %s", id(loop))
        except Exception as e:
            logger.warning(f"Error disconnecting Redis pool for loop {id(loop)}: {e}")


# Legacy function name for backward compatibility (if needed elsewhere)
async def close_redis_client(loop_id: Optional[int] = None) -> None:
    """
    Legacy function for closing Redis clients.
    
    Note: This function is deprecated. Use close_redis_for_current_loop() instead.
    The loop_id parameter is ignored - this always closes the current loop's client.
    """
    if loop_id is not None:
        logger.warning("close_redis_client(loop_id=...) is deprecated - use close_redis_for_current_loop() instead")
    await close_redis_for_current_loop()
