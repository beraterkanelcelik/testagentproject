"""
Supervisor agent for routing messages to appropriate sub-agents.
"""
from typing import List, Dict, Any
from langchain_core.messages import BaseMessage, AIMessage
from app.agents.agents.base import BaseAgent
from app.core.logging import get_logger

logger = get_logger(__name__)


class SupervisorAgent(BaseAgent):
    """
    Supervisor agent that routes user messages to appropriate sub-agents.
    """
    
    # Available agents
    AVAILABLE_AGENTS = {
        "greeter": "Provides welcome messages and guidance. Use when user needs help or is starting.",
        "gmail": "Handles email-related tasks. Use when user asks about emails, messages, or mail.",
        # Future agents can be added here
    }
    
    def __init__(self):
        super().__init__(
            name="supervisor",
            description="Routes user messages to appropriate sub-agents",
            temperature=0.3  # Lower temperature for more consistent routing
        )
    
    def get_system_prompt(self) -> str:
        """Get system prompt for supervisor agent."""
        agents_list = "\n".join([
            f"- {name}: {desc}" 
            for name, desc in self.AVAILABLE_AGENTS.items()
        ])
        
        return f"""You are a supervisor agent that routes user messages to the appropriate sub-agent.

Available agents:
{agents_list}

Your task is to analyze the user's message and determine which agent should handle it.
Consider:
- User intent and what they're asking for
- Whether this is a first message or help request (→ greeter)
- Whether it's email-related (→ gmail)
- If unclear, route to greeter for guidance

Respond with ONLY the agent name (e.g., "greeter" or "gmail"). Do not include any other text."""
    
    def route_message(self, messages: List[BaseMessage]) -> str:
        """
        Route message to appropriate agent.
        
        Args:
            messages: Conversation messages
            
        Returns:
            Agent name to route to
        """
        try:
            # Get routing decision from LLM
            response = self.invoke(messages)
            
            # Extract agent name from response
            agent_name = response.content.strip().lower()
            logger.debug(f"Supervisor routing decision: {agent_name}")
            
            # Validate agent name
            if agent_name in self.AVAILABLE_AGENTS:
                return agent_name
            
            # Default to greeter if invalid
            logger.warning(f"Invalid agent name '{agent_name}' from supervisor, defaulting to greeter")
            return "greeter"
        except Exception as e:
            logger.error(f"Error in supervisor route_message: {e}", exc_info=True)
            return "greeter"
    
    def get_tools(self) -> List:
        """Supervisor doesn't need tools."""
        return []
