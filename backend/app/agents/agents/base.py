"""
Base agent class for all agents.
"""
from abc import ABC, abstractmethod
from typing import List, Iterator
import os
import json
from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, AIMessage
from langchain_core.tools import BaseTool
from app.agents.config import (
    OPENAI_API_KEY,
    OPENAI_MODEL,
    LANGCHAIN_TRACING_V2,
    LANGCHAIN_PROJECT,
)
from app.core.logging import get_logger

logger = get_logger(__name__)

# Enable LangSmith tracing if configured (optional, for compatibility)
if LANGCHAIN_TRACING_V2:
    os.environ['LANGCHAIN_TRACING_V2'] = 'true'
    os.environ['LANGCHAIN_PROJECT'] = LANGCHAIN_PROJECT
    logger.info(f"LangSmith tracing enabled for project: {LANGCHAIN_PROJECT}")


class BaseAgent(ABC):
    """
    Abstract base class for all agents.
    Provides common functionality for LLM integration and tool handling.
    """
    
    def __init__(self, name: str, description: str, temperature: float = 0.7, model_name: str = None):
        """
        Initialize base agent.
        
        Args:
            name: Agent name/identifier
            description: Agent description for routing
            temperature: LLM temperature
            model_name: Optional model name (defaults to OPENAI_MODEL)
        """
        self.name = name
        self.description = description
        self._model_name = model_name or OPENAI_MODEL
        
        # LLM initialization - callbacks are passed via config at invocation time
        # This allows LangGraph to handle callback propagation automatically
        self.llm = ChatOpenAI(
            model=self._model_name,
            temperature=temperature,
            api_key=OPENAI_API_KEY,
            streaming=True,
            stream_usage=True,  # Enable token usage in streaming responses
        )
    
    @abstractmethod
    def get_system_prompt(self) -> str:
        """Get system prompt for this agent."""
        pass
    
    def get_tools(self) -> List[BaseTool]:
        """
        Get tools available to this agent.
        Override in subclasses to provide agent-specific tools.
        """
        return []
    
    def invoke(self, messages: List[BaseMessage], **kwargs) -> AIMessage:
        """
        Simplified invoke using LangChain's built-in handling.
        
        Args:
            messages: List of conversation messages
            **kwargs: Additional arguments including config (callbacks, run_id, metadata)
            
        Returns:
            AI response message
        """
        try:
            logger.debug(f"Invoking {self.name} agent with {len(messages)} messages")
            
            # Add system prompt as first message if not present
            system_prompt = self.get_system_prompt()
            if system_prompt:
                from langchain_core.messages import SystemMessage
                # Check if system message already exists
                if not messages or not isinstance(messages[0], SystemMessage) or messages[0].content != system_prompt:
                    messages = [SystemMessage(content=system_prompt)] + messages
            
            # Get tools for this agent
            tools = self.get_tools()
            
            # Bind tools to LLM if available
            if tools:
                llm_with_tools = self.llm.bind_tools(tools)
                logger.debug(f"{self.name} agent using {len(tools)} tools")
            else:
                llm_with_tools = self.llm
            
            # Invoke LLM - pass through config from kwargs
            # LangChain handles chunk accumulation automatically with invoke()
            invoke_kwargs = {}
            if 'config' in kwargs:
                invoke_kwargs['config'] = kwargs['config']
            
            # Use invoke() directly - LangChain handles everything automatically
            response = llm_with_tools.invoke(messages, **invoke_kwargs)
            
            logger.debug(f"[AGENT_INVOKE] {self.name} agent response generated successfully")
            return response
        except Exception as e:
            logger.error(f"Error invoking {self.name} agent: {e}", exc_info=True)
            raise
    
    async def astream(self, messages: List[BaseMessage], **kwargs):
        """
        Stream using LangChain's astream_events for proper event handling.
        
        Args:
            messages: List of conversation messages
            **kwargs: Additional arguments including config (callbacks, run_id, metadata)
            
        Yields:
            Structured streaming events
        """
        # Add system prompt
        system_prompt = self.get_system_prompt()
        if system_prompt:
            from langchain_core.messages import SystemMessage
            messages = [SystemMessage(content=system_prompt)] + messages
        
        # Get tools
        tools = self.get_tools()
        
        # Bind tools if available
        if tools:
            llm_with_tools = self.llm.bind_tools(tools)
        else:
            llm_with_tools = self.llm
        
        # Use astream_events for structured streaming
        stream_kwargs = {}
        if 'config' in kwargs:
            stream_kwargs['config'] = kwargs['config']
        
        async for event in llm_with_tools.astream_events(messages, version="v2", **stream_kwargs):
            yield event
    
    def stream(self, messages: List[BaseMessage], **kwargs) -> Iterator[BaseMessage]:
        """
        Stream agent response (synchronous version for backward compatibility).
        
        Args:
            messages: List of conversation messages
            **kwargs: Additional arguments including config (callbacks, run_id, metadata)
            
        Yields:
            Streaming message chunks
        """
        # Add system prompt
        system_prompt = self.get_system_prompt()
        if system_prompt:
            from langchain_core.messages import SystemMessage
            messages = [SystemMessage(content=system_prompt)] + messages
        
        # Get tools
        tools = self.get_tools()
        
        # Bind tools if available
        if tools:
            llm_with_tools = self.llm.bind_tools(tools)
        else:
            llm_with_tools = self.llm
        
        # Stream response - pass through config from kwargs
        # LangGraph handles callback propagation automatically
        stream_kwargs = {}
        if 'config' in kwargs:
            stream_kwargs['config'] = kwargs['config']
        
        for chunk in llm_with_tools.stream(messages, **stream_kwargs):
            yield chunk
