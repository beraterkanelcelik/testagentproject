"""
Supervisor agent for routing messages to appropriate sub-agents.
"""
from typing import List
from langchain_core.messages import BaseMessage, AIMessage
from app.agents.agents.base import BaseAgent
from app.core.logging import get_logger

logger = get_logger(__name__)


class SupervisorAgent(BaseAgent):
    """
    Supervisor agent that routes user messages to appropriate sub-agents.
    """
    
    # Available agents - can be moved to config or registry in future
    AVAILABLE_AGENTS = {
        "greeter": "Provides welcome messages and guidance. Use when user needs help or is starting.",
        "search": "Searches through user's uploaded documents and answers questions using RAG. Use when user asks about their documents, wants to search for information, or asks questions that might be in their uploaded files.",
        "gmail": "Handles email-related tasks. Use when user asks about emails, messages, or mail.",
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
- Whether user wants to search documents or ask questions about their uploaded files (→ search)
- Questions about people, entities, facts, or information that might be in documents (→ search)
- "Who is X?", "What is X?", "Tell me about X" type questions (→ search)
- Whether it's email-related (→ gmail)
- If unclear, route to greeter for guidance

IMPORTANT: Questions asking about specific people, entities, or facts (e.g., "who is X?", "what is X?", "tell me about X") should be routed to the search agent, as they likely need to search through uploaded documents.

Respond with ONLY the agent name (e.g., "greeter", "search", or "gmail"). Do not include any other text."""
    
    def route_message(self, messages: List[BaseMessage], **kwargs) -> str:
        """
        Route message to appropriate agent.
        
        Args:
            messages: Conversation messages
            **kwargs: Additional arguments including config (callbacks, run_id, metadata)
            
        Returns:
            Agent name to route to
        """
        try:
            # Get the latest user message for keyword-based routing
            latest_message = None
            if messages:
                # Find the last HumanMessage
                for msg in reversed(messages):
                    if hasattr(msg, 'content') and msg.content:
                        latest_message = msg.content.lower().strip()
                        break
            
            # Explicit keyword-based routing for common search queries
            # This ensures questions about people/entities route to search agent
            if latest_message:
                search_keywords = [
                    "who is", "what is", "tell me about", "who are", "what are",
                    "search for", "find information about", "look up", "information about"
                ]
                if any(latest_message.startswith(keyword) for keyword in search_keywords):
                    logger.info(f"Keyword-based routing: routing '{latest_message[:50]}...' to search agent")
                    return "search"
            
            # Get routing decision from LLM
            # Pass through config (including callbacks) from LangGraph
            response = self.invoke(messages, **kwargs)
            
            # Extract agent name from response
            if not response or not hasattr(response, 'content') or not response.content:
                logger.warning("Supervisor response is empty or invalid, defaulting to greeter")
                return "greeter"
            
            agent_name = response.content.strip().lower()
            logger.info(f"Supervisor routing decision: '{agent_name}' for message: '{latest_message[:50] if latest_message else 'N/A'}...'")
            
            # Handle None or empty string
            if not agent_name or agent_name == "none":
                logger.warning("Supervisor returned 'none' or empty, defaulting to greeter")
                return "greeter"
            
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
