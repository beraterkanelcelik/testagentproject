"""
Langfuse AI tracing and observability hooks (v3 SDK).

SDK v3 uses OpenTelemetry and works with Langfuse server v3+.
Reference: https://python.reference.langfuse.com/langfuse
"""
from typing import Optional, Dict, Any
from langfuse import get_client
from langfuse.langchain import CallbackHandler
from app.core.config import (
    LANGFUSE_PUBLIC_KEY,
    LANGFUSE_SECRET_KEY,
    LANGFUSE_BASE_URL,
    LANGFUSE_ENABLED
)
from app.core.logging import get_logger

logger = get_logger(__name__)


def get_langfuse_client():
    """
    Get the Langfuse client instance using singleton pattern.
    
    SDK v3: get_client() reads from environment variables automatically.
    Returns None if Langfuse is disabled or not configured.
    
    Returns:
        Langfuse client instance or None
    """
    if not LANGFUSE_ENABLED:
        return None
    
    if not LANGFUSE_PUBLIC_KEY or not LANGFUSE_SECRET_KEY:
        logger.warning("Langfuse keys not configured")
        return None
    
    try:
        # SDK v3: get_client() reads from environment automatically
        # Environment variables should be set: LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_BASE_URL
        return get_client()
    except Exception as e:
        logger.error(f"Failed to get Langfuse client: {e}", exc_info=True)
        return None


def get_callback_handler() -> Optional[CallbackHandler]:
    """
    Get Langfuse CallbackHandler for LangChain integration.
    
    SDK v3: CallbackHandler reads from environment variables automatically.
    No constructor arguments needed.
    
    Returns:
        CallbackHandler instance or None if disabled
    """
    if not LANGFUSE_ENABLED:
        return None
    
    if not LANGFUSE_PUBLIC_KEY or not LANGFUSE_SECRET_KEY:
        return None
    
    try:
        # SDK v3: CallbackHandler reads from environment automatically
        return CallbackHandler()
    except Exception as e:
        logger.error(f"Failed to create CallbackHandler: {e}", exc_info=True)
        return None


def prepare_trace_context(
    user_id: int,
    session_id: Optional[int] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Prepare trace context for propagate_attributes().
    
    This returns a dictionary that can be used with propagate_attributes()
    to set user_id, session_id, and metadata on traces.
    
    Args:
        user_id: User ID
        session_id: Optional session ID
        metadata: Optional additional metadata
        
    Returns:
        Dictionary with user_id, session_id, and metadata for propagate_attributes()
    """
    context = {
        "user_id": str(user_id),
    }
    
    if session_id:
        context["session_id"] = str(session_id)
    
    if metadata:
        # Convert all metadata values to strings (required by propagate_attributes)
        context["metadata"] = {
            k: str(v) if not isinstance(v, str) else v
            for k, v in metadata.items()
        }
    
    return context


def flush_traces():
    """
    Flush all pending traces to Langfuse.
    
    This ensures traces are sent immediately rather than waiting for background processes.
    Should be called in short-lived applications or before shutdown.
    """
    if not LANGFUSE_ENABLED:
        return
    
    try:
        client = get_langfuse_client()
        if client and hasattr(client, 'flush'):
            client.flush()
            logger.debug("Flushed Langfuse traces")
    except Exception as e:
        logger.error(f"Failed to flush Langfuse traces: {e}", exc_info=True)


def shutdown_client():
    """
    Gracefully shutdown the Langfuse client.
    
    This flushes all pending data and waits for background threads to finish.
    Should be called before application exit.
    """
    if not LANGFUSE_ENABLED:
        return
    
    try:
        client = get_langfuse_client()
        if client and hasattr(client, 'shutdown'):
            client.shutdown()
            logger.debug("Shutdown Langfuse client")
    except Exception as e:
        logger.error(f"Failed to shutdown Langfuse client: {e}", exc_info=True)
