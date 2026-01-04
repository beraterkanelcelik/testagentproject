"""
PostgreSQL checkpoint adapter for LangGraph.
"""
from typing import Optional
from contextlib import contextmanager
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.base import BaseCheckpointSaver
from app.settings import DATABASES
from app.core.logging import get_logger

logger = get_logger(__name__)

# Get database connection settings
db_config = DATABASES['default']
db_url = (
    f"postgresql://{db_config['USER']}:{db_config['PASSWORD']}"
    f"@{db_config['HOST']}:{db_config['PORT']}/{db_config['NAME']}"
)

_setup_done = False  # Track if setup has been done


@contextmanager
def get_checkpoint_saver():
    """
    Get PostgreSQL checkpoint saver as a context manager.
    
    Note: PostgresSaver.from_conn_string() returns a context manager.
    We use it as a context manager to ensure proper connection handling.
    """
    global _setup_done
    
    try:
        # PostgresSaver.from_conn_string() returns a context manager
        # We use it as a context manager to ensure connection stays open
        with PostgresSaver.from_conn_string(db_url) as saver:
            # Setup tables on first use (one-time operation)
            if not _setup_done:
                try:
                    saver.setup()
                    _setup_done = True
                    logger.info("Checkpoint tables setup completed")
                except Exception as setup_error:
                    logger.warning(f"Setup failed (tables may already exist): {setup_error}")
                    _setup_done = True  # Mark as done to avoid repeated attempts
            
            yield saver
    except Exception as e:
        logger.error(f"Failed to get checkpoint saver: {e}", exc_info=True)
        # Yield None to allow graph to work without checkpoint
        yield None


def get_checkpoint_config(chat_session_id: int):
    """
    Get checkpoint configuration for a chat session.
    Uses chat_session_id as the thread_id for checkpoint isolation.
    """
    return {
        "configurable": {
            "thread_id": f"chat_session_{chat_session_id}",
        }
    }
