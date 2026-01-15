"""
Unit tests for task functions.
"""
import unittest
from unittest.mock import Mock, patch, MagicMock
from django.test import TestCase

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from app.agents.functional.tasks.supervisor import route_to_agent
from app.agents.functional.tasks.tools import execute_tools
from app.agents.functional.models import RoutingDecision, ToolResult
from tests.test_helpers import get_test_config, create_test_entrypoint


class TestRouteToAgent(TestCase):
    """Test route_to_agent task."""

    @patch('app.agents.functional.tasks.supervisor.SupervisorAgent')
    def test_route_to_agent_success(self, mock_supervisor_class):
        """Test successful routing."""
        # Setup mock supervisor
        mock_supervisor = Mock()
        mock_decision = Mock()
        mock_decision.agent = "search"
        mock_decision.requires_clarification = False
        mock_decision.confidence = 0.95
        mock_supervisor.route_message.return_value = mock_decision
        mock_supervisor_class.return_value = mock_supervisor
        
        # Test - wrap task in entrypoint for testing
        messages = [HumanMessage(content="Search for documents")]
        test_entrypoint = create_test_entrypoint(route_to_agent)
        result = test_entrypoint.invoke(messages, config=get_test_config())
        
        # Verify
        self.assertIsInstance(result, RoutingDecision)
        self.assertEqual(result.agent, "search")
        self.assertFalse(result.require_clarification)
        mock_supervisor.route_message.assert_called_once()

    @patch('app.agents.functional.tasks.supervisor.SupervisorAgent')
    def test_route_to_agent_with_clarification(self, mock_supervisor_class):
        """Test routing with clarification request."""
        # Setup mock supervisor
        mock_supervisor = Mock()
        mock_decision = Mock()
        mock_decision.agent = "greeter"
        mock_decision.requires_clarification = True
        mock_decision.clarification_question = "What do you want to search for?"
        mock_decision.confidence = 0.5  # Add confidence to avoid format error
        mock_supervisor.route_message.return_value = mock_decision
        mock_supervisor_class.return_value = mock_supervisor
        
        # Test
        messages = [HumanMessage(content="Search")]
        test_entrypoint = create_test_entrypoint(route_to_agent)
        result = test_entrypoint.invoke(messages, config=get_test_config())
        
        # Verify
        self.assertTrue(result.require_clarification)

    @patch('app.agents.functional.tasks.supervisor.SupervisorAgent')
    def test_route_to_agent_exception_fallback(self, mock_supervisor_class):
        """Test fallback to greeter on exception."""
        # Setup mock to raise exception
        mock_supervisor = Mock()
        mock_supervisor.route_message.side_effect = Exception("Routing failed")
        mock_supervisor_class.return_value = mock_supervisor
        
        # Test
        messages = [HumanMessage(content="Test")]
        test_entrypoint = create_test_entrypoint(route_to_agent)
        result = test_entrypoint.invoke(messages, config=get_test_config())
        
        # Verify fallback
        self.assertEqual(result.agent, "greeter")

    @patch('app.agents.functional.tasks.supervisor.SupervisorAgent')
    def test_route_to_agent_extracts_query(self, mock_supervisor_class):
        """Test that query is extracted from messages."""
        # Setup mock supervisor
        mock_supervisor = Mock()
        mock_decision = Mock()
        mock_decision.agent = "greeter"
        mock_decision.requires_clarification = False
        mock_supervisor.route_message.return_value = mock_decision
        mock_supervisor_class.return_value = mock_supervisor
        
        # Test
        messages = [
            SystemMessage(content="You are a helpful assistant"),
            HumanMessage(content="Hello, how are you?")
        ]
        test_entrypoint = create_test_entrypoint(route_to_agent)
        result = test_entrypoint.invoke(messages, config=get_test_config())
        
        # Verify query is extracted from last human message
        self.assertEqual(result.query, "Hello, how are you?")

    @patch('app.agents.functional.tasks.supervisor.SupervisorAgent')
    def test_route_to_agent_with_config(self, mock_supervisor_class):
        """Test routing with config parameter."""
        # Setup mock supervisor
        mock_supervisor = Mock()
        mock_decision = Mock()
        mock_decision.agent = "search"
        mock_decision.requires_clarification = False
        mock_supervisor.route_message.return_value = mock_decision
        mock_supervisor_class.return_value = mock_supervisor
        
        # Test
        messages = [HumanMessage(content="Test")]
        config = get_test_config()
        test_entrypoint = create_test_entrypoint(route_to_agent)
        result = test_entrypoint.invoke(messages, config=config)
        
        # Verify config was passed (LangGraph may wrap it, so check it exists)
        mock_supervisor.route_message.assert_called_once()
        call_args = mock_supervisor.route_message.call_args
        self.assertIn('config', call_args[1])
        # Config is passed, but may be wrapped by LangGraph
        self.assertIsNotNone(call_args[1].get('config'))


class TestExecuteTools(TestCase):
    """Test execute_tools task."""

    @patch('app.agents.functional.tasks.tools.get_agent')
    @patch('app.agents.functional.tasks.tools.ToolNode')
    def test_execute_tools_success(self, mock_tool_node_class, mock_get_agent):
        """Test successful tool execution."""
        # Setup mock agent
        mock_agent = Mock()
        mock_tool = Mock()
        mock_tool.name = "test_tool"
        mock_agent.get_tools.return_value = [mock_tool]
        mock_get_agent.return_value = mock_agent
        
        # Setup mock ToolNode
        from langchain_core.messages import ToolMessage
        mock_tool_node = Mock()
        mock_tool_message = ToolMessage(
            content="Tool output",
            tool_call_id="call-123",
            name="test_tool"
        )
        mock_tool_node.invoke.return_value = {
            "messages": [mock_tool_message]
        }
        mock_tool_node_class.return_value = mock_tool_node
        
        # Test
        tool_calls = [
            {"id": "call-123", "name": "test_tool", "args": {"param": "value"}}
        ]
        test_entrypoint = create_test_entrypoint(execute_tools)
        # Pass args as tuple for positional arguments
        results = test_entrypoint.invoke((tool_calls, "search", 1), config=get_test_config())
        
        # Verify
        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], ToolResult)
        self.assertEqual(results[0].tool, "test_tool")
        self.assertEqual(results[0].output, "Tool output")
        self.assertEqual(results[0].tool_call_id, "call-123")

    @patch('app.agents.functional.tasks.tools.get_agent')
    def test_execute_tools_no_tools_available(self, mock_get_agent):
        """Test execution when agent has no tools."""
        # Setup mock agent with no tools
        mock_agent = Mock()
        mock_agent.get_tools.return_value = []
        mock_get_agent.return_value = mock_agent
        
        # Test
        tool_calls = [{"id": "call-123", "name": "test_tool", "args": {}}]
        test_entrypoint = create_test_entrypoint(execute_tools)
        results = test_entrypoint.invoke((tool_calls, "greeter", 1), config=get_test_config())
        
        # Verify empty results
        self.assertEqual(len(results), 0)

    @patch('app.agents.functional.tasks.tools.get_agent')
    @patch('app.agents.functional.tasks.tools.ToolNode')
    def test_execute_tools_exception(self, mock_tool_node_class, mock_get_agent):
        """Test tool execution with exception."""
        # Setup mock agent
        mock_agent = Mock()
        mock_tool = Mock()
        mock_agent.get_tools.return_value = [mock_tool]
        mock_get_agent.return_value = mock_agent
        
        # Setup mock ToolNode to raise exception
        mock_tool_node = Mock()
        mock_tool_node.invoke.side_effect = Exception("Tool execution failed")
        mock_tool_node_class.return_value = mock_tool_node
        
        # Test
        tool_calls = [
            {"id": "call-123", "name": "test_tool", "args": {}}
        ]
        test_entrypoint = create_test_entrypoint(execute_tools)
        # Pass args as tuple for positional arguments
        results = test_entrypoint.invoke((tool_calls, "search", 1), config=get_test_config())
        
        # Verify error results
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].error, "Tool execution failed")
        self.assertIsNone(results[0].output)

    @patch('app.agents.functional.tasks.tools.get_agent')
    @patch('app.agents.functional.tasks.tools.ToolNode')
    @patch('app.observability.metrics.record_tool_call')
    def test_execute_tools_metrics_recording(self, mock_record, mock_tool_node_class, mock_get_agent):
        """Test that metrics are recorded for tool execution."""
        # Setup mock agent
        mock_agent = Mock()
        mock_tool = Mock()
        mock_agent.get_tools.return_value = [mock_tool]
        mock_get_agent.return_value = mock_agent
        
        # Setup mock ToolNode
        mock_tool_node = Mock()
        mock_tool_message = Mock()
        mock_tool_message.tool_call_id = "call-123"
        mock_tool_message.name = "test_tool"
        mock_tool_message.content = "Output"
        mock_tool_node.invoke.return_value = {"messages": [mock_tool_message]}
        mock_tool_node_class.return_value = mock_tool_node
        
        # Test
        tool_calls = [{"id": "call-123", "name": "test_tool", "args": {}}]
        test_entrypoint = create_test_entrypoint(execute_tools)
        test_entrypoint.invoke((tool_calls, "search", 1), config=get_test_config())
        
        # Verify metrics were recorded
        mock_record.assert_called()

    @patch('app.agents.functional.tasks.tools.get_agent')
    @patch('app.agents.functional.tasks.tools.ToolNode')
    def test_execute_tools_multiple_tools(self, mock_tool_node_class, mock_get_agent):
        """Test execution of multiple tools."""
        # Setup mock agent
        mock_agent = Mock()
        mock_tool1 = Mock()
        mock_tool1.name = "tool1"
        mock_tool2 = Mock()
        mock_tool2.name = "tool2"
        mock_agent.get_tools.return_value = [mock_tool1, mock_tool2]
        mock_get_agent.return_value = mock_agent
        
        # Setup mock ToolNode
        from langchain_core.messages import ToolMessage
        mock_tool_node = Mock()
        mock_tool_message1 = ToolMessage(
            content="Output 1",
            tool_call_id="call-1",
            name="tool1"
        )
        mock_tool_message2 = ToolMessage(
            content="Output 2",
            tool_call_id="call-2",
            name="tool2"
        )
        mock_tool_node.invoke.return_value = {
            "messages": [mock_tool_message1, mock_tool_message2]
        }
        mock_tool_node_class.return_value = mock_tool_node
        
        # Test
        tool_calls = [
            {"id": "call-1", "name": "tool1", "args": {}},
            {"id": "call-2", "name": "tool2", "args": {}}
        ]
        test_entrypoint = create_test_entrypoint(execute_tools)
        # Pass args as tuple for positional arguments
        results = test_entrypoint.invoke((tool_calls, "search", 1), config=get_test_config())
        
        # Verify both tools executed
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].tool, "tool1")
        self.assertEqual(results[1].tool, "tool2")
