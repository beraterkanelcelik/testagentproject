"""
Configuration utility module for loading and managing environment variables.

This module provides helpers for loading environment variables from .env files
and accessing configuration values throughout the application.
"""

import os
from typing import Optional, Any
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables from .env file
# This should be called once at application startup
load_dotenv()


def get_env_var(key: str, default: Optional[str] = None) -> Optional[str]:
    """
    Get an environment variable value.
    
    Args:
        key: The environment variable key
        default: Default value if key is not found
        
    Returns:
        The environment variable value or default
        
    Example:
        api_key = get_env_var("LANGCHAIN_API_KEY")
    """
    return os.getenv(key, default)


def get_env_var_required(key: str) -> str:
    """
    Get a required environment variable, raising error if not found.
    
    Args:
        key: The environment variable key
        
    Returns:
        The environment variable value
        
    Raises:
        ValueError: If the environment variable is not set
        
    Example:
        api_key = get_env_var_required("LANGCHAIN_API_KEY")
    """
    value = os.getenv(key)
    if value is None:
        raise ValueError(f"Required environment variable '{key}' is not set")
    return value


def get_env_bool(key: str, default: bool = False) -> bool:
    """
    Get an environment variable as a boolean.
    
    Args:
        key: The environment variable key
        default: Default value if key is not found
        
    Returns:
        Boolean value (true for "true", "1", "yes", "on"; false otherwise)
        
    Example:
        tracing_enabled = get_env_bool("LANGCHAIN_TRACING_V2", default=False)
    """
    value = os.getenv(key, str(default)).lower()
    return value in ("true", "1", "yes", "on")


def get_env_int(key: str, default: Optional[int] = None) -> Optional[int]:
    """
    Get an environment variable as an integer.
    
    Args:
        key: The environment variable key
        default: Default value if key is not found or cannot be converted
        
    Returns:
        Integer value or default
        
    Example:
        port = get_env_int("PORT", default=8000)
    """
    value = os.getenv(key)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def validate_config() -> bool:
    """
    Validate that required configuration is present.
    
    Returns:
        True if all required configuration is present, False otherwise
        
    TODO: Add validation logic for required environment variables
    """
    # TODO: Add validation for required environment variables
    # Example:
    # required_vars = ["LANGCHAIN_API_KEY"]
    # for var in required_vars:
    #     if not get_env_var(var):
    #         return False
    return True
