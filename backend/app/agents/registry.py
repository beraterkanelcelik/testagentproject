"""
Generic agent registry for unified agent management.

This module now uses AgentFactory for agent creation, maintaining backward compatibility.
"""
from typing import Optional
from app.agents.agents.base import BaseAgent
from app.agents.config import OPENAI_MODEL
from app.agents.factory import AgentFactory
from app.core.logging import get_logger

logger = get_logger(__name__)


def get_agent(
    agent_name: str,
    user_id: Optional[int] = None,
    model_name: Optional[str] = None
) -> BaseAgent:
    """
    Get agent instance using AgentFactory (backward compatibility wrapper).

    Args:
        agent_name: Name of agent (e.g., "greeter", "search")
        user_id: User ID for agent context
        model_name: Model name (defaults to OPENAI_MODEL)

    Returns:
        Agent instance (created via factory, not cached)

    Raises:
        ValueError: If agent_name is unknown and no fallback available
    """
    # Normalize inputs
    model_name = model_name or OPENAI_MODEL
    
    # Use factory to create agent (prefer create() over get_cached() for correctness)
    try:
        agent = AgentFactory.create(
            agent_name=agent_name,
            user_id=user_id,
            model_name=model_name
        )
        logger.debug(f"Created agent via factory: {agent_name} (user_id={user_id}, model={model_name})")
        return agent
    except ValueError as e:
        logger.error(f"Failed to create agent {agent_name}: {e}")
        raise


def get_available_agents() -> list[str]:
    """Get list of available agent names"""
    return list(AgentFactory._registry.keys())


def clear_agent_cache():
    """Clear the agent cache (clears factory cache)"""
    AgentFactory.get_cached.cache_clear()
    logger.info("Agent factory cache cleared")


# Backward compatibility: keep old function names
def register_agent(name: str, agent_class: type[BaseAgent]):
    """Register an agent class (delegates to factory)."""
    AgentFactory.register(name, agent_class)
