"""
Centralized settings management for the application.

This module provides a single source of truth for all application
configuration, including LangSmith tracing settings.
"""

from typing import Optional
from dataclasses import dataclass

# TODO: Import config utilities when implemented
# from utils.config import get_env_var, get_env_bool, get_env_var_required


@dataclass
class LangSmithSettings:
    """
    LangSmith configuration settings.
    
    LangSmith is used for tracing, debugging, and monitoring LLM applications.
    These settings control how LangSmith integrates with the application.
    """
    api_key: str
    tracing_enabled: bool = True
    project_name: str = "test-agent-project"
    endpoint: Optional[str] = None
    environment: Optional[str] = None
    
    @classmethod
    def from_env(cls) -> "LangSmithSettings":
        """
        Create LangSmithSettings from environment variables.
        
        Returns:
            LangSmithSettings instance populated from environment
            
        TODO: Implement environment variable loading
        """
        # TODO: Load from environment variables
        # return cls(
        #     api_key=get_env_var_required("LANGCHAIN_API_KEY"),
        #     tracing_enabled=get_env_bool("LANGCHAIN_TRACING_V2", default=True),
        #     project_name=get_env_var("LANGCHAIN_PROJECT", default="test-agent-project"),
        #     endpoint=get_env_var("LANGCHAIN_ENDPOINT"),
        #     environment=get_env_var("LANGCHAIN_ENV")
        # )
        return cls(
            api_key="",  # Placeholder
            tracing_enabled=True,
            project_name="test-agent-project"
        )


@dataclass
class AppSettings:
    """
    Application-wide settings.
    
    This class holds all configuration for the application,
    including LangSmith settings and other app-specific values.
    """
    langsmith: LangSmithSettings
    
    # TODO: Add other application settings as needed
    # log_level: str = "INFO"
    # debug_mode: bool = False
    
    @classmethod
    def from_env(cls) -> "AppSettings":
        """
        Create AppSettings from environment variables.
        
        Returns:
            AppSettings instance populated from environment
        """
        return cls(
            langsmith=LangSmithSettings.from_env()
        )


# Global settings instance
# This will be initialized when the module is imported
# TODO: Initialize from environment variables
settings: AppSettings = AppSettings.from_env()


def reload_settings() -> None:
    """
    Reload settings from environment variables.
    
    This is useful when environment variables change at runtime.
    """
    global settings
    settings = AppSettings.from_env()
