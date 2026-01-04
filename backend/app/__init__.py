"""
Django app initialization.
"""
# Initialize logging early
from app.core import logging  # noqa: F401

default_app_config = 'app.apps.AppConfig'
