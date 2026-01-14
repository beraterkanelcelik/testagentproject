"""
Agent configuration and settings.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# OpenAI Configuration
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
OPENAI_MODEL = os.getenv('OPENAI_MODEL', 'gpt-4o-mini')

# LangSmith Configuration (optional, kept for compatibility)
LANGCHAIN_API_KEY = os.getenv('LANGCHAIN_API_KEY')
LANGCHAIN_TRACING_V2 = os.getenv('LANGCHAIN_TRACING_V2', 'false').lower() == 'true'
LANGCHAIN_PROJECT = os.getenv('LANGCHAIN_PROJECT', 'agent-playground')
LANGCHAIN_ENDPOINT = os.getenv('LANGCHAIN_ENDPOINT', 'https://api.smith.langchain.com')

# Langfuse Configuration (primary tracing solution)
from app.core.config import LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST, LANGFUSE_ENABLED

# Checkpoint Configuration
CHECKPOINT_TABLE_NAME = 'checkpoints'
CHECKPOINT_SCHEMA = 'public'

# Agent Configuration
MAX_ITERATIONS = 50  # Maximum graph iterations
STREAMING_ENABLED = True

# Model context window sizes (tokens)
MODEL_CONTEXT_WINDOWS = {
    "gpt-4": 8192,
    "gpt-4-32k": 32768,
    "gpt-4-turbo": 1280,
    "gpt-4-turbo-preview": 128000,
    "gpt-4o": 128000,
    "gpt-4o-mini": 128000,
    "gpt-3.5-turbo": 16385,
    "gpt-3.5-turbo-16k": 16385,
    # Add more models as needed
}


def get_model_context_window(model_name: str) -> int:
    """
    Get context window size for a model.

    Args:
        model_name: Model identifier (e.g., "gpt-4o-mini")

    Returns:
        Context window size in tokens
    """
    # Try exact match first
    if model_name in MODEL_CONTEXT_WINDOWS:
        return MODEL_CONTEXT_WINDOWS[model_name]

    # Try prefix match (e.g., "gpt-4-0125-preview" -> "gpt-4-turbo")
    for key in MODEL_CONTEXT_WINDOWS:
        if model_name.startswith(key):
            return MODEL_CONTEXT_WINDOWS[key]

    # Default to 128k for modern models
    return 1280


# Validate required configuration
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY environment variable is required")
