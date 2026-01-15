"""
Test helpers for LangGraph task testing.
"""
from langchain_core.runnables import RunnableConfig
from langgraph.func import entrypoint


def get_test_config() -> RunnableConfig:
    """Get a test config for LangGraph tasks."""
    return RunnableConfig(
        configurable={"thread_id": "test_thread"},
        run_id="test_run"
    )


def create_test_entrypoint(task_func):
    """
    Create a test entrypoint wrapper for a task function.
    
    This allows testing @task functions by wrapping them in an @entrypoint.
    The entrypoint takes a single input (can be a dict for keyword args or tuple for positional).
    Config is automatically available to tasks via LangGraph context, so we don't pass it explicitly.
    """
    @entrypoint()
    def test_wrapper(input_data):
        # Handle dict (keyword args) or tuple (positional args)
        if isinstance(input_data, dict):
            # Remove config from dict if present (it's passed to invoke, not task)
            # Config is available via LangGraph context automatically
            task_kwargs = {k: v for k, v in input_data.items() if k != 'config'}
            future = task_func(**task_kwargs)
        elif isinstance(input_data, tuple):
            # For positional args, unpack tuple
            # Don't include config in tuple - it's available via context
            future = task_func(*input_data)
        else:
            # Single positional arg
            future = task_func(input_data)
        return future.result()
    
    return test_wrapper
