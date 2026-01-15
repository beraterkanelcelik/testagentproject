"""
Unit tests for workflow utility functions.
"""
import unittest
from unittest.mock import Mock, patch, MagicMock
from django.test import TestCase

from app.agents.functional.workflow import (
    extract_tool_proposals,
    tool_requires_approval,
    is_auto_executable,
    _should_generate_plan,
    partition_tools,
    extract_response_from_chunk,
    extract_interrupt_value,
    build_db_url,
    TOOLS_REQUIRING_APPROVAL,
)
from app.agents.functional.models import AgentResponse, ToolProposal


class TestExtractToolProposals(TestCase):
    """Test extract_tool_proposals function."""

    def test_extract_tool_proposals_with_name_key(self):
        """Test extraction with 'name' key."""
        tool_calls = [
            {"name": "rag_retrieval_tool", "args": {"query": "test"}},
            {"name": "get_current_time", "args": {}},
        ]
        proposals = extract_tool_proposals(tool_calls)
        
        self.assertEqual(len(proposals), 2)
        self.assertEqual(proposals[0].tool, "rag_retrieval_tool")
        self.assertEqual(proposals[0].props, {"query": "test"})
        self.assertEqual(proposals[1].tool, "get_current_time")

    def test_extract_tool_proposals_with_tool_key(self):
        """Test extraction with 'tool' key (alternative format)."""
        tool_calls = [
            {"tool": "rag_retrieval_tool", "args": {"query": "test"}},
        ]
        proposals = extract_tool_proposals(tool_calls)
        
        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0].tool, "rag_retrieval_tool")

    def test_extract_tool_proposals_empty_list(self):
        """Test extraction with empty list."""
        proposals = extract_tool_proposals([])
        self.assertEqual(len(proposals), 0)

    def test_extract_tool_proposals_missing_name(self):
        """Test extraction skips tools without name or tool key."""
        tool_calls = [
            {"args": {"query": "test"}},  # Missing name/tool
            {"name": "valid_tool", "args": {}},
        ]
        proposals = extract_tool_proposals(tool_calls)
        
        # Should only extract the valid tool
        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0].tool, "valid_tool")


class TestToolRequiresApproval(TestCase):
    """Test tool_requires_approval function."""

    def test_tool_in_approval_set(self):
        """Test tool that requires approval."""
        self.assertTrue(tool_requires_approval("get_current_time"))

    def test_tool_not_in_approval_set(self):
        """Test tool that doesn't require approval."""
        self.assertFalse(tool_requires_approval("rag_retrieval_tool"))

    @patch('app.agents.tools.registry.tool_registry')
    def test_tool_from_registry_with_requires_approval(self, mock_registry):
        """Test tool from registry with requires_approval attribute."""
        mock_tool = Mock()
        mock_tool.requires_approval = True
        mock_registry.get_tool_by_name.return_value = mock_tool
        
        self.assertTrue(tool_requires_approval("custom_tool"))

    @patch('app.agents.tools.registry.tool_registry')
    def test_tool_from_registry_without_requires_approval(self, mock_registry):
        """Test tool from registry without requires_approval attribute."""
        mock_tool = Mock()
        # Mock tool without requires_approval attribute (hasattr returns False)
        if hasattr(mock_tool, 'requires_approval'):
            delattr(mock_tool, 'requires_approval')
        mock_registry.get_tool_by_name.return_value = mock_tool
        
        self.assertFalse(tool_requires_approval("custom_tool"))

    @patch('app.agents.tools.registry.tool_registry')
    def test_tool_not_in_registry(self, mock_registry):
        """Test tool not found in registry."""
        mock_registry.get_tool_by_name.return_value = None
        
        self.assertFalse(tool_requires_approval("unknown_tool"))

    @patch('app.agents.tools.registry.tool_registry')
    def test_registry_import_error(self, mock_registry):
        """Test handling of registry import error."""
        mock_registry.get_tool_by_name.side_effect = ImportError("Module not found")
        
        # Should not raise, just return False
        self.assertFalse(tool_requires_approval("any_tool"))


class TestIsAutoExecutable(TestCase):
    """Test is_auto_executable function."""

    def test_approval_required_tool_not_auto_executable(self):
        """Test that tools requiring approval are not auto-executable."""
        self.assertFalse(is_auto_executable("get_current_time", "greeter"))

    def test_non_approval_tool_not_auto_executable(self):
        """Test that even non-approval tools are not auto-executable by default."""
        self.assertFalse(is_auto_executable("rag_retrieval_tool", "search"))


class TestShouldGeneratePlan(TestCase):
    """Test _should_generate_plan function."""

    def test_simple_query_no_plan(self):
        """Test that simple queries don't need planning."""
        query = "Hello"
        self.assertFalse(_should_generate_plan(query, "greeter"))

    def test_multi_step_keywords_triggers_plan(self):
        """Test that multi-step keywords trigger planning."""
        query = "First search for documents, then email the results"
        self.assertTrue(_should_generate_plan(query, "greeter"))

    def test_complex_query_triggers_plan(self):
        """Test that complex queries trigger planning."""
        query = "This is a very long query with multiple sentences. It has many words and requires several steps to complete. First we need to do this. Then we need to do that. Finally we need to do something else."
        self.assertTrue(_should_generate_plan(query, "greeter"))

    def test_short_query_no_plan(self):
        """Test that short queries don't need planning."""
        query = "What is Python?"
        self.assertFalse(_should_generate_plan(query, "greeter"))

    def test_multi_step_keyword_then(self):
        """Test 'then' keyword triggers planning."""
        query = "Search for documents then summarize them"
        self.assertTrue(_should_generate_plan(query, "greeter"))


class TestPartitionTools(TestCase):
    """Test partition_tools function."""

    def test_partition_approval_tools(self):
        """Test partitioning tools requiring approval."""
        tool_calls = [
            {"name": "get_current_time", "args": {}},
            {"name": "rag_retrieval_tool", "args": {"query": "test"}},
        ]
        result = partition_tools(tool_calls, "greeter")
        
        self.assertEqual(len(result["approval"]), 1)
        self.assertEqual(result["approval"][0]["name"], "get_current_time")
        self.assertEqual(len(result["auto"]), 0)
        self.assertEqual(len(result["manual"]), 1)
        self.assertEqual(result["manual"][0]["name"], "rag_retrieval_tool")

    def test_partition_all_types(self):
        """Test partitioning with all tool types."""
        tool_calls = [
            {"name": "get_current_time", "args": {}},  # Approval
            {"name": "rag_retrieval_tool", "args": {}},  # Manual
        ]
        result = partition_tools(tool_calls, "greeter")
        
        self.assertEqual(len(result["approval"]), 1)
        self.assertEqual(len(result["auto"]), 0)
        self.assertEqual(len(result["manual"]), 1)

    def test_partition_empty_list(self):
        """Test partitioning empty tool list."""
        result = partition_tools([], "greeter")
        
        self.assertEqual(len(result["approval"]), 0)
        self.assertEqual(len(result["auto"]), 0)
        self.assertEqual(len(result["manual"]), 0)

    def test_partition_tool_without_name(self):
        """Test partitioning with tool using 'tool' key instead of 'name'."""
        tool_calls = [
            {"tool": "get_current_time", "args": {}},
        ]
        result = partition_tools(tool_calls, "greeter")
        
        self.assertEqual(len(result["approval"]), 1)


class TestExtractResponseFromChunk(TestCase):
    """Test extract_response_from_chunk function."""

    def test_extract_agent_response_direct(self):
        """Test extraction when chunk is AgentResponse."""
        response = AgentResponse(
            type="answer",
            reply="Hello",
            agent_name="greeter"
        )
        result = extract_response_from_chunk(response)
        
        self.assertIsNotNone(result)
        self.assertEqual(result.reply, "Hello")
        self.assertEqual(result.agent_name, "greeter")

    def test_extract_from_dict_with_workflow_key(self):
        """Test extraction from dict with 'ai_agent_workflow' key."""
        response = AgentResponse(
            type="answer",
            reply="Hello",
            agent_name="greeter"
        )
        chunk = {"ai_agent_workflow": response}
        result = extract_response_from_chunk(chunk)
        
        self.assertIsNotNone(result)
        self.assertEqual(result.reply, "Hello")

    def test_extract_from_dict_with_response_data(self):
        """Test extraction from dict with response data."""
        chunk = {
            "ai_agent_workflow": {
                "type": "answer",
                "reply": "Hello",
                "agent_name": "greeter"
            }
        }
        result = extract_response_from_chunk(chunk)
        
        self.assertIsNotNone(result)
        self.assertEqual(result.reply, "Hello")

    def test_extract_from_dict_direct(self):
        """Test extraction from dict with response keys."""
        chunk = {
            "type": "answer",
            "reply": "Hello",
            "agent_name": "greeter"
        }
        result = extract_response_from_chunk(chunk)
        
        self.assertIsNotNone(result)
        self.assertEqual(result.reply, "Hello")

    def test_extract_none_for_invalid_chunk(self):
        """Test extraction returns None for invalid chunk."""
        result = extract_response_from_chunk("invalid")
        self.assertIsNone(result)

    def test_extract_none_for_empty_dict(self):
        """Test extraction returns None for empty dict."""
        result = extract_response_from_chunk({})
        self.assertIsNone(result)


class TestExtractInterruptValue(TestCase):
    """Test extract_interrupt_value function."""

    def test_extract_from_tuple_with_value(self):
        """Test extraction from tuple format."""
        interrupt_obj = Mock()
        interrupt_obj.value = {"type": "tool_approval", "tools": []}
        interrupt_raw = (interrupt_obj,)
        
        result = extract_interrupt_value(interrupt_raw)
        
        self.assertEqual(result["type"], "tool_approval")

    def test_extract_from_dict_with_value(self):
        """Test extraction from dict with 'value' key."""
        interrupt_raw = {
            "value": {"type": "tool_approval", "tools": []}
        }
        result = extract_interrupt_value(interrupt_raw)
        
        self.assertEqual(result["type"], "tool_approval")

    def test_extract_from_dict_direct(self):
        """Test extraction from dict with type key."""
        interrupt_raw = {
            "type": "tool_approval",
            "tools": []
        }
        result = extract_interrupt_value(interrupt_raw)
        
        self.assertEqual(result["type"], "tool_approval")

    def test_extract_from_list(self):
        """Test extraction from list format."""
        interrupt_raw = [
            {
                "value": {"type": "tool_approval", "tools": []}
            }
        ]
        result = extract_interrupt_value(interrupt_raw)
        
        self.assertEqual(result["type"], "tool_approval")

    def test_extract_fallback(self):
        """Test fallback for unknown format."""
        interrupt_raw = "unknown_format"
        result = extract_interrupt_value(interrupt_raw)
        
        self.assertEqual(result, {})


class TestBuildDbUrl(TestCase):
    """Test build_db_url function."""

    @patch('app.settings.DATABASES')
    def test_build_db_url(self, mock_databases):
        """Test database URL construction."""
        mock_databases.__getitem__.return_value = {
            'USER': 'testuser',
            'PASSWORD': 'testpass',
            'HOST': 'localhost',
            'PORT': '5432',
            'NAME': 'testdb'
        }
        
        url = build_db_url()
        
        self.assertIn("testuser", url)
        self.assertIn("testpass", url)
        self.assertIn("localhost", url)
        self.assertIn("5432", url)
        self.assertIn("testdb", url)
        self.assertTrue(url.startswith("postgresql://"))
