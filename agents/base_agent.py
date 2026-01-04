"""
Base agent class for AI agents using LangChain and LangGraph.

This module provides an abstract base class that defines the interface
and common functionality for all AI agents in the project.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, List
from langchain_core.runnables import Runnable
from langgraph.graph import StateGraph

# TODO: Import logger and config when implemented
# from utils.logger import get_logger
# from config.settings import settings

# logger = get_logger(__name__)


class BaseAgent(ABC):
    """
    Abstract base class for AI agents.
    
    This class defines the common interface and structure for all agents.
    Subclasses should implement the abstract methods to create specific
    agent behaviors.
    
    Attributes:
        name: Name identifier for the agent
        description: Human-readable description of the agent's purpose
        graph: LangGraph StateGraph instance for the agent's workflow
        chain: LangChain Runnable chain for processing
    """
    
    def __init__(
        self,
        name: str = "BaseAgent",
        description: str = "Base agent implementation"
    ) -> None:
        """
        Initialize the base agent.
        
        Args:
            name: Name identifier for the agent
            description: Human-readable description of the agent's purpose
        """
        self.name = name
        self.description = description
        self.graph: Optional[StateGraph] = None
        self.chain: Optional[Runnable] = None
        
        # TODO: Initialize logger
        # self.logger = get_logger(self.__class__.__name__)
        
        # Build the agent graph and chain
        self._build_graph()
        self._build_chain()
    
    @abstractmethod
    def _build_graph(self) -> None:
        """
        Build the LangGraph StateGraph for the agent.
        
        This method should define the agent's state structure and workflow.
        Subclasses must implement this method.
        
        TODO: Implement graph building logic
        - Define state schema
        - Add nodes for agent steps
        - Add edges to connect nodes
        - Compile the graph
        """
        pass
    
    @abstractmethod
    def _build_chain(self) -> None:
        """
        Build the LangChain Runnable chain for the agent.
        
        This method should create the processing chain that the agent uses.
        Subclasses must implement this method.
        
        TODO: Implement chain building logic
        - Define chain components
        - Connect components in sequence
        - Set up error handling
        """
        pass
    
    @abstractmethod
    def process(self, input_data: str, **kwargs: Any) -> str:
        """
        Process input and return agent response.
        
        This is the main entry point for interacting with the agent.
        Subclasses must implement this method.
        
        Args:
            input_data: The input string to process
            **kwargs: Additional keyword arguments for processing
            
        Returns:
            The agent's response as a string
            
        TODO: Implement processing logic
        - Validate input
        - Invoke graph or chain
        - Handle errors
        - Return formatted response
        """
        pass
    
    def get_state(self) -> Dict[str, Any]:
        """
        Get the current state of the agent.
        
        Returns:
            Dictionary containing the agent's current state
            
        TODO: Implement state retrieval
        """
        return {
            "name": self.name,
            "description": self.description,
            "graph_initialized": self.graph is not None,
            "chain_initialized": self.chain is not None
        }
    
    def reset(self) -> None:
        """
        Reset the agent to its initial state.
        
        TODO: Implement reset logic
        - Clear any internal state
        - Reinitialize components if needed
        """
        # TODO: Implement reset logic
        pass
    
    def __repr__(self) -> str:
        """Return string representation of the agent."""
        return f"{self.__class__.__name__}(name='{self.name}')"
