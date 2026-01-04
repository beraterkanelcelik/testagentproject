"""
LangGraph state definition.
"""
from typing import TypedDict, List, Optional, Dict, Any
from langchain_core.messages import BaseMessage


class AgentState(TypedDict):
    """
    State structure for the agent graph.
    """
    messages: List[BaseMessage]  # Conversation messages
    current_agent: Optional[str]  # Name of current executing agent
    chat_session_id: int  # Link to ChatSession
    user_id: int  # Link to User
    tool_calls: List[Dict[str, Any]]  # List of tool invocations
    metadata: Dict[str, Any]  # Additional state data
    next_agent: Optional[str]  # Next agent to route to (set by router)
