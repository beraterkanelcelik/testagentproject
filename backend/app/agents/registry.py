"""
Generic agent registry for unified agent management.

This module provides a centralized registry for all agents, eliminating
hardcoded if/elif chains and separate agent caches.
"""
from typing import Dict, Type, Optional
from app.agents.agents.base import BaseAgent
from app.agents.config import OPENAI_MODEL
from app.core.logging import get_logger

logger = get_logger(__name__)

# Agent registry - populate from imports
# To add a new agent: just import and add to this dict!
AGENT_REGISTRY: Dict[str, Type[BaseAgent]] = {}


def register_agent(name: str, agent_class: Type[BaseAgent]):
    """
    Register an agent class by name.

    Args:
        name: Agent identifier (e.g., "greeter", "search")
        agent_class: Agent class (subclass of BaseAgent)
    """
    AGENT_REGISTRY[name] = agent_class
    logger.info(f"Registered agent: {name} -> {agent_class.__name__}")


# Lazy imports to avoid circular dependencies
def _ensure_agents_registered():
    """Ensure all agents are registered (lazy initialization)"""
    if AGENT_REGISTRY:
        return  # Already registered

    # Import and register agents
    from app.agents.agents.greeter import GreeterAgent
    from app.agents.agents.search import SearchAgent
    from app.agents.agents.supervisor import SupervisorAgent

    register_agent("greeter", GreeterAgent)
    register_agent("search", SearchAgent)
    register_agent("supervisor", SupervisorAgent)


# Single unified cache for all agents
_agent_cache: Dict[str, BaseAgent] = {}


def get_agent(
    agent_name: str,
    user_id: Optional[int] = None,
    model_name: Optional[str] = None
) -> BaseAgent:
    """
    Get agent instance with caching (generic, works for ANY agent).

    Args:
        agent_name: Name of agent (e.g., "greeter", "search")
        user_id: User ID for agent context
        model_name: Model name (defaults to OPENAI_MODEL)

    Returns:
        Agent instance (from cache or newly created)

    Raises:
        ValueError: If agent_name is unknown and no fallback available
    """
    # Ensure agents are registered
    _ensure_agents_registered()

    # Normalize inputs
    model_name = model_name or OPENAI_MODEL
    cache_key = f"{agent_name}:{user_id}:{model_name}"

    # Check cache
    if cache_key in _agent_cache:
        return _agent_cache[cache_key]

    # Get agent class from registry
    agent_class = AGENT_REGISTRY.get(agent_name)

    if not agent_class:
        logger.warning(f"Unknown agent '{agent_name}', falling back to 'greeter'")
        agent_class = AGENT_REGISTRY.get("greeter")

        if not agent_class:
            raise ValueError(f"Agent '{agent_name}' not found and no fallback available")

    # Create and cache agent instance
    agent = agent_class(user_id=user_id, model_name=model_name)
    _agent_cache[cache_key] = agent

    logger.debug(f"Created agent: {agent_name} (cache_key={cache_key})")
    return agent


def clear_agent_cache():
    """Clear the agent cache (useful for testing or memory management)"""
    global _agent_cache
    _agent_cache.clear()
    logger.info("Agent cache cleared")


def get_available_agents() -> list[str]:
    """Get list of available agent names"""
    _ensure_agents_registered()
    return list(AGENT_REGISTRY.keys())
