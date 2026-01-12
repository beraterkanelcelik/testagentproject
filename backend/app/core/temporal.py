"""
Temporal client singleton for workflow management.
CRITICAL: Use threading.Lock instead of asyncio.Lock to avoid event loop binding issues.
"""
import threading
from temporalio.client import Client
from temporalio.service import RetryConfig, KeepAliveConfig
from app.settings import TEMPORAL_ADDRESS
from app.core.logging import get_logger

logger = get_logger(__name__)

_temporal_client: Client | None = None
_lock = threading.Lock()  # Thread-safe lock, not loop-bound


async def get_temporal_client() -> Client:
    """
    Get or create Temporal client singleton.
    
    Uses threading.Lock (not asyncio.Lock) to avoid event loop binding issues.
    Temporal clients are thread-safe and can be used across event loops.
    
    CRITICAL: Handles race condition where multiple coroutines try to create client concurrently.
    The first one to finish stores it, others close their duplicate and use the stored one.
    
    Returns:
        Temporal client instance
    """
    global _temporal_client
    
    # Fast path: client already exists
    if _temporal_client is not None:
        return _temporal_client
    
    # Double-check pattern: acquire lock to check again
    # We'll create the client OUTSIDE the lock to avoid blocking threads during async I/O
    # Then acquire lock again to store it (or close duplicate if another coroutine won)
    with _lock:
        # Double-check after acquiring lock
        if _temporal_client is not None:
            return _temporal_client
        # Release lock (exiting 'with' block) - now create client outside lock
    
    # Create client OUTSIDE the lock (don't block other threads during async I/O)
    try:
        # Configure retry policy for client operations (in milliseconds)
        retry_config = RetryConfig(
            initial_interval_millis=1000,  # 1 second
            randomization_factor=0.2,
            multiplier=2.0,
            max_interval_millis=30000,  # 30 seconds
            max_elapsed_time_millis=300000,  # 5 minutes total
            max_retries=60,
        )
        
        # Configure keep-alive to maintain connection and detect drops (in milliseconds)
        keep_alive_config = KeepAliveConfig(
            interval_millis=30000,  # Check every 30 seconds
            timeout_millis=15000,  # Timeout after 15 seconds
        )
        
        logger.info(f"Connecting to Temporal at {TEMPORAL_ADDRESS}")
        new_client = await Client.connect(
            TEMPORAL_ADDRESS,
            namespace="default",
            retry_config=retry_config,
            keep_alive_config=keep_alive_config,
        )
        
        # Now acquire lock again to store the client (or close it if another coroutine won)
        with _lock:
            # Check if another coroutine created it while we were connecting
            if _temporal_client is None:
                _temporal_client = new_client
                logger.info("Temporal client created successfully")
                return _temporal_client
            else:
                # Another coroutine created it first, close ours and use the existing one
                logger.debug("Temporal client was created by another coroutine while we were connecting, closing duplicate")
                await new_client.close()
                return _temporal_client
    except Exception as e:
        logger.error(f"Failed to create Temporal client: {e}", exc_info=True)
        raise


async def close_temporal_client():
    """Close Temporal client connection."""
    global _temporal_client
    
    if _temporal_client:
        try:
            await _temporal_client.close()
            _temporal_client = None
            logger.info("Temporal client closed")
        except Exception as e:
            logger.error(f"Error closing Temporal client: {e}", exc_info=True)
