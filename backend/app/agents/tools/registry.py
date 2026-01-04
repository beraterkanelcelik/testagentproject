"""
Tool registry for dynamic tool discovery and management.
"""
from typing import Dict, List, Optional
from langchain_core.tools import BaseTool
from app.agents.tools.base import AgentTool


class ToolRegistry:
    """
    Registry for managing agent tools.
    Supports tool registration, discovery, and retrieval by agent name.
    """
    
    def __init__(self):
        """Initialize tool registry."""
        self._tools: Dict[str, List[AgentTool]] = {}  # agent_name -> list of tools
        self._all_tools: Dict[str, AgentTool] = {}  # tool_name -> tool instance
    
    def register_tool(self, tool: AgentTool, agent_names: List[str]):
        """
        Register a tool for one or more agents.
        
        Args:
            tool: Tool instance to register
            agent_names: List of agent names that can use this tool
        """
        tool_name = tool.name
        
        # Store in all tools
        self._all_tools[tool_name] = tool
        
        # Register for each agent
        for agent_name in agent_names:
            if agent_name not in self._tools:
                self._tools[agent_name] = []
            self._tools[agent_name].append(tool)
    
    def unregister_tool(self, tool_name: str):
        """
        Unregister a tool from all agents.
        
        Args:
            tool_name: Name of tool to unregister
        """
        if tool_name in self._all_tools:
            del self._all_tools[tool_name]
        
        # Remove from all agent tool lists
        for agent_name in self._tools:
            self._tools[agent_name] = [
                t for t in self._tools[agent_name] if t.name != tool_name
            ]
    
    def get_tools_for_agent(self, agent_name: str) -> List[BaseTool]:
        """
        Get LangChain tools for a specific agent.
        
        Args:
            agent_name: Name of the agent
            
        Returns:
            List of BaseTool instances
        """
        tools = self._tools.get(agent_name, [])
        return [tool.get_tool() for tool in tools]
    
    def get_all_tools(self) -> List[BaseTool]:
        """
        Get all registered tools.
        
        Returns:
            List of all BaseTool instances
        """
        return [tool.get_tool() for tool in self._all_tools.values()]
    
    def get_tool_by_name(self, tool_name: str) -> Optional[AgentTool]:
        """
        Get tool instance by name.
        
        Args:
            tool_name: Name of the tool
            
        Returns:
            Tool instance or None if not found
        """
        return self._all_tools.get(tool_name)


# Global tool registry instance
tool_registry = ToolRegistry()
