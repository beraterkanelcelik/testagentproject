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
SECRET_KEY = os.environ['DJANGO_SECRET_KEY']
DEBUG = os.getenv('DEBUG', 'False') == 'True'

# Database configuration
DB_NAME = os.environ['DB_NAME']
DB_USER = os.environ['DB_USER']
DB_PASSWORD = os.environ['DB_PASSWORD']
DB_HOST = os.environ['DB_HOST']
DB_PORT = os.environ['DB_PORT']

# Langfuse configuration (v3 SDK)
# Reference: https://python.reference.langfuse.com/langfuse
LANGFUSE_PUBLIC_KEY = os.getenv('LANGFUSE_PUBLIC_KEY', '')
LANGFUSE_SECRET_KEY = os.getenv('LANGFUSE_SECRET_KEY', '')
LANGFUSE_BASE_URL = os.getenv('LANGFUSE_BASE_URL', 'http://langfuse:3000')
LANGFUSE_ENABLED = os.getenv('LANGFUSE_ENABLED', 'true') == 'true'

# OpenAI configuration
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '')
