"""
Task functions for LangGraph Functional API.

This module maintains backward compatibility by re-exporting tasks from the new modular structure.
New code should import directly from app.agents.functional.tasks.* modules.
"""
# Re-export all functions from new modular structure
from app.agents.functional.tasks.supervisor import route_to_agent
from app.agents.functional.tasks.agent import execute_agent, refine_with_tool_results
from app.agents.functional.tasks.tools import execute_tools
from app.agents.functional.tasks.common import (
    load_messages_task,
    save_message_task,
    check_summarization_needed_task,
    truncate_tool_output,
)

# Backward compatibility aliases - point to the new function names
supervisor_task = route_to_agent
agent_task = execute_agent
agent_with_tool_results_task = refine_with_tool_results
tool_execution_task = execute_tools

# Export all symbols
__all__ = [
    # New names (preferred)
    "route_to_agent",
    "execute_agent",
    "refine_with_tool_results",
    "execute_tools",
    "load_messages_task",
    "save_message_task",
    "check_summarization_needed_task",
    "truncate_tool_output",
    # Backward compatibility aliases (deprecated)
    "supervisor_task",
    "agent_task",
    "agent_with_tool_results_task",
    "tool_execution_task",
]


# Legacy function wrappers for very old code that may still call these with different signatures
# These should be removed once all calling code is updated
from typing import List, Dict, Any, Optional
from langchain_core.messages import BaseMessage
from langchain_core.runnables import RunnableConfig
from app.agents.functional.models import AgentResponse, ToolResult
from app.core.logging import get_logger

logger = get_logger(__name__)


def generic_agent_task(
    agent_name: str,
    query: str,
    messages: List[BaseMessage],
    user_id: Optional[int],
    model_name: Optional[str] = None,
    config: Optional[RunnableConfig] = None
) -> AgentResponse:
    """
    Legacy wrapper for generic agent execution.
    DEPRECATED: Use execute_agent() from tasks.agent instead.

    Args:
        agent_name: Name of agent to execute
        query: User query
        messages: Conversation history
        user_id: User ID
        model_name: Optional model name
        config: Optional runtime config

    Returns:
        AgentResponse
    """
    logger.warning("generic_agent_task is deprecated, use execute_agent() instead")
    return execute_agent(
        agent_name=agent_name,
        messages=messages,
        user_id=user_id,
        model_name=model_name,
        config=config
    )
