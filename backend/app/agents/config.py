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

# Validate required configuration
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY environment variable is required")
