"""
Greeter agent for welcoming users and providing guidance.
"""
from typing import List
from langchain_core.messages import BaseMessage
from app.agents.agents.base import BaseAgent
from app.core.logging import get_logger

logger = get_logger(__name__)


class GreeterAgent(BaseAgent):
    """
    Agent that provides welcome messages and guidance to users.
    """
    
    def __init__(self):
        super().__init__(
            name="greeter",
            description="Provides welcome messages, guidance, and helps users get started",
            temperature=0.7
        )
    
    def get_system_prompt(self) -> str:
        """Get system prompt for greeter agent."""
        return """You are a friendly and helpful greeter agent. Your role is to:
1. Welcome users warmly when they first interact
2. Provide guidance on how to use the system
3. Explain what capabilities are available
4. Help users understand how to interact with the assistant
5. Be concise but friendly in your responses

Keep responses helpful and encouraging. If the user asks about specific features or agents, 
you can mention that the supervisor will route them to the appropriate agent."""
    
    def get_tools(self) -> List:
        """Greeter agent doesn't need tools initially."""
        return []
