"""
Configuration management.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Django settings
SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'django-insecure-change-this-in-production')
DEBUG = os.getenv('DEBUG', 'True') == 'True'

# Database configuration
DB_NAME = os.getenv('DB_NAME', 'ai_agents_db')
DB_USER = os.getenv('DB_USER', 'postgres')
DB_PASSWORD = os.getenv('DB_PASSWORD', 'postgres')
DB_HOST = os.getenv('DB_HOST', 'db')
DB_PORT = os.getenv('DB_PORT', '5432')

# LangSmith configuration (optional, kept for compatibility)
LANGCHAIN_API_KEY = os.getenv('LANGCHAIN_API_KEY', '')
LANGCHAIN_TRACING_V2 = os.getenv('LANGCHAIN_TRACING_V2', 'false') == 'true'
LANGCHAIN_PROJECT = os.getenv('LANGCHAIN_PROJECT', 'django-app')
LANGCHAIN_ENDPOINT = os.getenv('LANGCHAIN_ENDPOINT', '')

# Langfuse configuration (v3 SDK)
# Reference: https://python.reference.langfuse.com/langfuse
LANGFUSE_PUBLIC_KEY = os.getenv('LANGFUSE_PUBLIC_KEY', '')
LANGFUSE_SECRET_KEY = os.getenv('LANGFUSE_SECRET_KEY', '')
# Use LANGFUSE_BASE_URL (preferred in v3) or fallback to LANGFUSE_HOST (deprecated but supported)
LANGFUSE_BASE_URL = os.getenv('LANGFUSE_BASE_URL', os.getenv('LANGFUSE_HOST', 'http://langfuse:3000'))
LANGFUSE_HOST = LANGFUSE_BASE_URL  # Keep for backward compatibility
LANGFUSE_ENABLED = os.getenv('LANGFUSE_ENABLED', 'true') == 'true'

# OpenAI configuration
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '')
