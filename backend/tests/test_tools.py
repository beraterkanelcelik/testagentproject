"""
Unit tests for tool registry and tools.
"""
import unittest
from unittest.mock import Mock, patch, MagicMock
from django.test import TestCase

from langchain_core.tools import BaseTool

from app.agents.tools.registry import ToolRegistry, tool_registry
from app.agents.tools.base import AgentTool


class MockTool(AgentTool):
    """Mock tool for testing."""
    
    @property
    def name(self) -> str:
        return "mock_tool"
    
    @property
    def description(self) -> str:
        return "A mock tool for testing"
    
    def get_tool(self) -> BaseTool:
        from langchain_core.tools import tool
        
        @tool
        def mock_tool_function(param: str) -> str:
            """Mock tool function."""
            return f"Result: {param}"
        
        return mock_tool_function


class TestToolRegistry(TestCase):
    """Test ToolRegistry class."""

    def setUp(self):
        """Set up test fixtures."""
        self.registry = ToolRegistry()

    def test_register_tool(self):
        """Test registering a tool."""
        tool = MockTool()
        
        self.registry.register_tool(tool, ["agent1", "agent2"])
        
        # Verify tool is registered
        self.assertEqual(self.registry.get_tool_by_name("mock_tool"), tool)
        self.assertEqual(len(self.registry.get_tools_for_agent("agent1")), 1)
        self.assertEqual(len(self.registry.get_tools_for_agent("agent2")), 1)

    def test_register_tool_multiple_agents(self):
        """Test registering tool for multiple agents."""
        tool = MockTool()
        
        self.registry.register_tool(tool, ["agent1", "agent2", "agent3"])
        
        # Verify tool is available for all agents
        for agent_name in ["agent1", "agent2", "agent3"]:
            tools = self.registry.get_tools_for_agent(agent_name)
            self.assertEqual(len(tools), 1)
            # Tools returned are LangChain tools (function names)
            self.assertEqual(tools[0].name, "mock_tool_function")

    def test_unregister_tool(self):
        """Test unregistering a tool."""
        tool = MockTool()
        
        self.registry.register_tool(tool, ["agent1"])
        self.assertEqual(len(self.registry.get_tools_for_agent("agent1")), 1)
        
        self.registry.unregister_tool("mock_tool")
        
        # Verify tool is removed
        self.assertIsNone(self.registry.get_tool_by_name("mock_tool"))
        self.assertEqual(len(self.registry.get_tools_for_agent("agent1")), 0)

    def test_get_tools_for_agent(self):
        """Test getting tools for a specific agent."""
        tool1 = MockTool()
        
        # Create a second tool with different name
        class MockTool2(AgentTool):
            @property
            def name(self) -> str:
                return "mock_tool_2"
            
            @property
            def description(self) -> str:
                return "A second mock tool"
            
            def get_tool(self) -> BaseTool:
                from langchain_core.tools import tool
                @tool
                def mock_tool_2_function(param: str) -> str:
                    """Mock tool 2 function for testing."""
                    return f"Result 2: {param}"
                return mock_tool_2_function
        
        tool2 = MockTool2()
        
        self.registry.register_tool(tool1, ["agent1"])
        self.registry.register_tool(tool2, ["agent1"])
        
        tools = self.registry.get_tools_for_agent("agent1")
        self.assertEqual(len(tools), 2)

    def test_get_tools_for_agent_empty(self):
        """Test getting tools for agent with no tools."""
        tools = self.registry.get_tools_for_agent("unknown_agent")
        self.assertEqual(len(tools), 0)

    def test_get_all_tools(self):
        """Test getting all registered tools."""
        tool1 = MockTool()
        
        # Create a second tool with different name
        class MockTool2(AgentTool):
            @property
            def name(self) -> str:
                return "mock_tool_2"
            
            @property
            def description(self) -> str:
                return "A second mock tool"
            
            def get_tool(self) -> BaseTool:
                from langchain_core.tools import tool
                @tool
                def mock_tool_2_function(param: str) -> str:
                    """Mock tool 2 function for testing."""
                    return f"Result 2: {param}"
                return mock_tool_2_function
        
        tool2 = MockTool2()
        
        self.registry.register_tool(tool1, ["agent1"])
        self.registry.register_tool(tool2, ["agent2"])
        
        all_tools = self.registry.get_all_tools()
        self.assertEqual(len(all_tools), 2)

    def test_get_tool_by_name(self):
        """Test getting tool by name."""
        tool = MockTool()
        
        self.registry.register_tool(tool, ["agent1"])
        
        retrieved_tool = self.registry.get_tool_by_name("mock_tool")
        self.assertEqual(retrieved_tool, tool)

    def test_get_tool_by_name_not_found(self):
        """Test getting tool that doesn't exist."""
        tool = self.registry.get_tool_by_name("nonexistent_tool")
        self.assertIsNone(tool)

    def test_register_multiple_tools_same_agent(self):
        """Test registering multiple tools for same agent."""
        tool1 = MockTool()
        
        # Create a second tool with different name
        class MockTool2(AgentTool):
            @property
            def name(self) -> str:
                return "mock_tool_2"
            
            @property
            def description(self) -> str:
                return "A second mock tool"
            
            def get_tool(self) -> BaseTool:
                from langchain_core.tools import tool
                @tool
                def mock_tool_2_function(param: str) -> str:
                    """Mock tool 2 function for testing."""
                    return f"Result 2: {param}"
                return mock_tool_2_function
        
        tool2 = MockTool2()
        
        self.registry.register_tool(tool1, ["agent1"])
        self.registry.register_tool(tool2, ["agent1"])
        
        tools = self.registry.get_tools_for_agent("agent1")
        self.assertEqual(len(tools), 2)


class TestGlobalToolRegistry(TestCase):
    """Test global tool_registry instance."""

    def test_global_registry_exists(self):
        """Test that global tool_registry exists."""
        self.assertIsNotNone(tool_registry)
        self.assertIsInstance(tool_registry, ToolRegistry)

    def test_global_registry_singleton(self):
        """Test that tool_registry is a singleton."""
        from app.agents.tools.registry import tool_registry as registry2
        
        self.assertIs(tool_registry, registry2)


class TestRAGTool(TestCase):
    """Test RAG retrieval tool."""

    def test_rag_tool_exists(self):
        """Test that RAG tool function can be imported."""
        from app.agents.tools.rag_tool import create_rag_tool
        
        # Test that function exists and can be called
        tool = create_rag_tool(user_id=1)
        self.assertIsNotNone(tool)
        self.assertIsInstance(tool, BaseTool)
        self.assertEqual(tool.name, "rag_retrieval_tool")


class TestTimeTool(TestCase):
    """Test time tool."""

    def test_time_tool_exists(self):
        """Test that TimeTool can be imported."""
        from app.agents.tools.time_tool import TimeTool
        
        tool = TimeTool()
        self.assertEqual(tool.name, "get_current_time")
        self.assertIsNotNone(tool.description)

    def test_time_tool_get_tool(self):
        """Test TimeTool.get_tool returns LangChain tool."""
        from app.agents.tools.time_tool import TimeTool
        
        tool = TimeTool()
        langchain_tool = tool.get_tool()
        
        self.assertIsInstance(langchain_tool, BaseTool)
        self.assertEqual(langchain_tool.name, "get_current_time")

    def test_time_tool_execution(self):
        """Test time tool execution."""
        from app.agents.tools.time_tool import TimeTool
        
        tool = TimeTool()
        langchain_tool = tool.get_tool()
        
        # Execute tool
        result = langchain_tool.invoke({})
        
        # Verify result is a string (time string)
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)


class TestAgentToolBase(TestCase):
    """Test AgentTool base class."""

    def test_agent_tool_is_abstract(self):
        """Test that AgentTool requires implementation."""
        from app.agents.tools.base import AgentTool
        
        # AgentTool should be an abstract base class
        with self.assertRaises(TypeError):
            # Cannot instantiate abstract class
            AgentTool()

    def test_agent_tool_interface(self):
        """Test that AgentTool defines required interface."""
        from app.agents.tools.base import AgentTool
        
        # Check required properties/methods
        self.assertTrue(hasattr(AgentTool, 'name'))
        self.assertTrue(hasattr(AgentTool, 'description'))
        self.assertTrue(hasattr(AgentTool, 'get_tool'))
