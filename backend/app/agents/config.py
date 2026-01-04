"""
Agent configuration and settings.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# OpenAI Configuration
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
OPENAI_MODEL = 'gpt-4o-mini-2024-07-18'  # Using available model (gpt-4.1-mini-2025-04-14 not available yet)

# LangSmith Configuration (optional, for tracing)
LANGCHAIN_API_KEY = os.getenv('LANGCHAIN_API_KEY')
LANGCHAIN_TRACING_V2 = os.getenv('LANGCHAIN_TRACING_V2', 'false').lower() == 'true'
LANGCHAIN_PROJECT = os.getenv('LANGCHAIN_PROJECT', 'test-agent-project')
LANGCHAIN_ENDPOINT = os.getenv('LANGCHAIN_ENDPOINT', 'https://api.smith.langchain.com')

# Checkpoint Configuration
CHECKPOINT_TABLE_NAME = 'checkpoints'
CHECKPOINT_SCHEMA = 'public'

# Agent Configuration
MAX_ITERATIONS = 50  # Maximum graph iterations
STREAMING_ENABLED = True

# Validate required configuration
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY environment variable is required")
