"""
Agent factory for creating agents with proper lifecycle management.
"""
from functools import lru_cache
from typing import Optional, Type, Dict
from langchain_core.runnables import RunnableConfig
from app.agents.agents.base import BaseAgent
from app.core.logging import get_logger

logger = get_logger(__name__)


class AgentFactory:
    """Factory for creating agents with proper lifecycle."""
    
    _registry: Dict[str, Type[BaseAgent]] = {}
    
    @classmethod
    def register(cls, name: str, agent_class: Type[BaseAgent]):
        """Register an agent class."""
        cls._registry[name] = agent_class
        logger.debug(f"Registered agent: {name} -> {agent_class.__name__}")
    
    @classmethod
    def create(
        cls,
        agent_name: str,
        user_id: Optional[int] = None,
        model_name: Optional[str] = None,
        config: Optional[RunnableConfig] = None
    ) -> BaseAgent:
        """
        Create agent instance (not cached - agents are lightweight).
        
        Args:
            agent_name: Name of agent to create
            user_id: Optional user ID
            model_name: Optional model name
            config: Optional runtime config (unused, kept for compatibility)
            
        Returns:
            Agent instance
        """
        agent_class = cls._registry.get(agent_name)
        if not agent_class:
            logger.warning(f"Unknown agent: {agent_name}, using greeter")
            agent_class = cls._registry.get("greeter")
            if not agent_class:
                raise ValueError(f"Agent '{agent_name}' not found and no fallback available")
        
        return agent_class(user_id=user_id, model_name=model_name)
    
    @classmethod
    @lru_cache(maxsize=32)
    def get_cached(
        cls,
        agent_name: str,
        user_id: Optional[int] = None,
        model_name: Optional[str] = None
    ) -> BaseAgent:
        """
        Get cached agent (use sparingly - prefer create()).
        
        Args:
            agent_name: Name of agent
            user_id: Optional user ID
            model_name: Optional model name
            
        Returns:
            Cached agent instance
        """
        return cls.create(agent_name, user_id, model_name)


# Auto-register agents on import
def _register_agents():
    """Register all available agents."""
    try:
        from app.agents.agents.greeter import GreeterAgent
        from app.agents.agents.search import SearchAgent
        from app.agents.agents.supervisor import SupervisorAgent
        
        AgentFactory.register("greeter", GreeterAgent)
        AgentFactory.register("search", SearchAgent)
        AgentFactory.register("supervisor", SupervisorAgent)
        
        logger.info("Agent factory: Registered agents")
    except Exception as e:
        logger.warning(f"Failed to register some agents: {e}")


# Register agents on module import
_register_agents()
