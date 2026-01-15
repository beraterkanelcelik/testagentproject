"""
Unit tests for planner functionality.
"""
import unittest
import json
from unittest.mock import Mock, patch, MagicMock, AsyncMock
from django.test import TestCase

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from app.agents.functional.tasks.planner import analyze_and_plan, PLANNING_SYSTEM_PROMPT
from tests.test_helpers import get_test_config, create_test_entrypoint


class TestAnalyzeAndPlan(TestCase):
    """Test analyze_and_plan task."""

    @patch('app.agents.factory.AgentFactory')
    def test_analyze_and_plan_no_plan_needed(self, mock_factory):
        """Test planning when no plan is needed."""
        # Setup mock planning agent
        mock_agent = Mock()
        mock_response = Mock()
        mock_response.content = json.dumps({
            "requires_plan": False,
            "reasoning": "Simple query",
            "plan": []
        })
        mock_agent.invoke.return_value = mock_response
        mock_factory.create.return_value = mock_agent
        
        # Test
        messages = [HumanMessage(content="What is Python?")]
        test_entrypoint = create_test_entrypoint(analyze_and_plan)
        result = test_entrypoint.invoke({"messages": messages, "user_id": 1}, config=get_test_config())
        
        # Verify
        self.assertFalse(result["requires_plan"])
        self.assertEqual(result["reasoning"], "Simple query")
        self.assertEqual(len(result["plan"]), 0)

    @patch('app.agents.factory.AgentFactory')
    def test_analyze_and_plan_with_plan(self, mock_factory):
        """Test planning when plan is needed."""
        # Setup mock planning agent
        mock_agent = Mock()
        plan_data = {
            "requires_plan": True,
            "reasoning": "Multi-step task",
            "plan": [
                {
                    "action": "tool",
                    "tool": "rag_retrieval_tool",
                    "props": {"query": "Python"},
                    "agent": "search",
                    "query": "Search for Python documents"
                },
                {
                    "action": "answer",
                    "answer": "Provide summary",
                    "agent": "greeter",
                    "query": "Summarize results"
                }
            ]
        }
        mock_response = Mock()
        mock_response.content = json.dumps(plan_data)
        mock_agent.invoke.return_value = mock_response
        mock_factory.create.return_value = mock_agent
        
        # Test
        messages = [HumanMessage(content="Search for Python docs and summarize")]
        test_entrypoint = create_test_entrypoint(analyze_and_plan)
        result = test_entrypoint.invoke({"messages": messages, "user_id": 1}, config=get_test_config())
        
        # Verify
        self.assertTrue(result["requires_plan"])
        self.assertEqual(len(result["plan"]), 2)
        self.assertEqual(result["plan"][0]["action"], "tool")
        self.assertEqual(result["plan"][1]["action"], "answer")

    @patch('app.agents.factory.AgentFactory')
    def test_analyze_and_plan_with_markdown_code_block(self, mock_factory):
        """Test parsing JSON from markdown code block."""
        # Setup mock planning agent
        mock_agent = Mock()
        plan_data = {
            "requires_plan": True,
            "reasoning": "Multi-step",
            "plan": []
        }
        mock_response = Mock()
        mock_response.content = f"```json\n{json.dumps(plan_data)}\n```"
        mock_agent.invoke.return_value = mock_response
        mock_factory.create.return_value = mock_agent
        
        # Test
        messages = [HumanMessage(content="Test")]
        test_entrypoint = create_test_entrypoint(analyze_and_plan)
        # Pass as dict to avoid config parameter conflict
        result = test_entrypoint.invoke({"messages": messages, "user_id": 1}, config=get_test_config())
        
        # Verify JSON was extracted from code block
        self.assertTrue(result["requires_plan"])

    @patch('app.agents.factory.AgentFactory')
    def test_analyze_and_plan_with_dict_response(self, mock_factory):
        """Test handling dict response (not string)."""
        # Setup mock planning agent
        mock_agent = Mock()
        plan_data = {
            "requires_plan": False,
            "reasoning": "Simple",
            "plan": []
        }
        mock_agent.invoke.return_value = plan_data
        mock_factory.create.return_value = mock_agent
        
        # Test
        messages = [HumanMessage(content="Test")]
        test_entrypoint = create_test_entrypoint(analyze_and_plan)
        # Pass as dict to avoid config parameter conflict
        result = test_entrypoint.invoke({"messages": messages, "user_id": 1}, config=get_test_config())
        
        # Verify
        self.assertFalse(result["requires_plan"])

    @patch('app.agents.factory.AgentFactory')
    def test_analyze_and_plan_json_decode_error(self, mock_factory):
        """Test handling JSON decode errors."""
        # Setup mock planning agent
        mock_agent = Mock()
        mock_response = Mock()
        mock_response.content = "Invalid JSON {"
        mock_agent.invoke.return_value = mock_response
        mock_factory.create.return_value = mock_agent
        
        # Test
        messages = [HumanMessage(content="Test")]
        test_entrypoint = create_test_entrypoint(analyze_and_plan)
        # Pass as dict to avoid config parameter conflict
        result = test_entrypoint.invoke({"messages": messages, "user_id": 1}, config=get_test_config())
        
        # Verify error handling
        self.assertFalse(result["requires_plan"])
        self.assertIn("Failed to parse", result["reasoning"])

    @patch('app.agents.factory.AgentFactory')
    def test_analyze_and_plan_invalid_response_format(self, mock_factory):
        """Test handling invalid response format."""
        # Setup mock planning agent
        mock_agent = Mock()
        mock_response = Mock()
        mock_response.content = "Not a dict or JSON"
        mock_agent.invoke.return_value = mock_response
        mock_factory.create.return_value = mock_agent
        
        # Test
        messages = [HumanMessage(content="Test")]
        test_entrypoint = create_test_entrypoint(analyze_and_plan)
        # Pass as dict to avoid config parameter conflict
        result = test_entrypoint.invoke({"messages": messages, "user_id": 1}, config=get_test_config())
        
        # Verify fallback
        self.assertFalse(result["requires_plan"])

    @patch('app.agents.factory.AgentFactory')
    def test_analyze_and_plan_exception_handling(self, mock_factory):
        """Test handling exceptions during planning."""
        # Setup mock planning agent to raise exception
        mock_agent = Mock()
        mock_agent.invoke.side_effect = Exception("Planning failed")
        mock_factory.create.return_value = mock_agent
        
        # Test
        messages = [HumanMessage(content="Test")]
        test_entrypoint = create_test_entrypoint(analyze_and_plan)
        # Pass as dict to avoid config parameter conflict
        result = test_entrypoint.invoke({"messages": messages, "user_id": 1}, config=get_test_config())
        
        # Verify error handling
        self.assertFalse(result["requires_plan"])
        self.assertIn("Planning failed", result["reasoning"])

    @patch('app.agents.factory.AgentFactory')
    def test_analyze_and_plan_adds_system_prompt(self, mock_factory):
        """Test that system prompt is added to messages."""
        # Setup mock planning agent
        mock_agent = Mock()
        mock_response = Mock()
        mock_response.content = json.dumps({
            "requires_plan": False,
            "reasoning": "Simple",
            "plan": []
        })
        mock_agent.invoke.return_value = mock_response
        mock_factory.create.return_value = mock_agent
        
        # Test
        messages = [HumanMessage(content="Test")]
        test_entrypoint = create_test_entrypoint(analyze_and_plan)
        test_entrypoint.invoke({"messages": messages, "user_id": 1}, config=get_test_config())
        
        # Verify system prompt was added
        self.assertTrue(mock_agent.invoke.called)
        call_args = mock_agent.invoke.call_args
        if call_args:
            # Check first positional arg (messages list)
            if call_args[0]:
                messages_arg = call_args[0][0]
                if isinstance(messages_arg, list) and len(messages_arg) > 0:
                    self.assertIsInstance(messages_arg[0], SystemMessage)
                    self.assertEqual(messages_arg[0].content, PLANNING_SYSTEM_PROMPT)

    @patch('app.agents.factory.AgentFactory')
    def test_analyze_and_plan_passes_config(self, mock_factory):
        """Test that config is passed to planning agent."""
        # Setup mock planning agent
        mock_agent = Mock()
        mock_response = Mock()
        mock_response.content = json.dumps({
            "requires_plan": False,
            "reasoning": "Simple",
            "plan": []
        })
        mock_agent.invoke.return_value = mock_response
        mock_factory.create.return_value = mock_agent
        
        # Test
        messages = [HumanMessage(content="Test")]
        config = RunnableConfig(run_id="test-run")
        test_entrypoint = create_test_entrypoint(analyze_and_plan)
        test_entrypoint.invoke({"messages": messages, "user_id": 1}, config=config)
        
        # Verify config was passed (LangGraph wraps it, so check it's in kwargs)
        call_kwargs = mock_agent.invoke.call_args[1]
        self.assertIn('config', call_kwargs)
        # Config is wrapped by LangGraph, so just verify it exists
        self.assertIsNotNone(call_kwargs.get('config'))

    @patch('app.agents.factory.AgentFactory')
    def test_analyze_and_plan_plan_steps_validation(self, mock_factory):
        """Test that plan steps are properly validated."""
        # Setup mock planning agent
        mock_agent = Mock()
        plan_data = {
            "requires_plan": True,
            "reasoning": "Multi-step",
            "plan": [
                {
                    "action": "tool",
                    "tool": "rag_retrieval_tool",
                    "props": {"query": "test"},
                    "agent": "search",
                    "query": "Search"
                }
            ]
        }
        mock_response = Mock()
        mock_response.content = json.dumps(plan_data)
        mock_agent.invoke.return_value = mock_response
        mock_factory.create.return_value = mock_agent
        
        # Test
        messages = [HumanMessage(content="Test")]
        test_entrypoint = create_test_entrypoint(analyze_and_plan)
        # Pass as dict to avoid config parameter conflict
        result = test_entrypoint.invoke({"messages": messages, "user_id": 1}, config=get_test_config())
        
        # Verify plan step structure
        self.assertTrue(result["requires_plan"])
        self.assertEqual(len(result["plan"]), 1)
        step = result["plan"][0]
        self.assertIn("action", step)
        self.assertIn("agent", step)
        self.assertIn("query", step)
