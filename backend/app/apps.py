"""
Django app configuration.
"""
from django.apps import AppConfig


class AppConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'app'
    verbose_name = 'Agent Playground'

    def ready(self):
        """Initialize app when Django is ready."""
        # Import logging to ensure it's configured
        from app.core import logging  # noqa: F401
