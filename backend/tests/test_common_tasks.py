"""
Unit tests for common task functions.
"""
import unittest
import json
from unittest.mock import Mock, patch, MagicMock
from django.test import TestCase

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from app.agents.functional.tasks.common import (
    truncate_tool_output,
    load_messages_task,
    check_summarization_needed_task,
    save_message_task,
    MAX_TOOL_OUTPUT_SIZE,
)
from app.agents.functional.models import AgentResponse
from tests.test_helpers import get_test_config, create_test_entrypoint


class TestTruncateToolOutput(TestCase):
    """Test truncate_tool_output function."""

    def test_truncate_small_output(self):
        """Test that small outputs are not truncated."""
        output = {"result": "Small output"}
        result = truncate_tool_output(output)
        
        self.assertEqual(result, output)

    def test_truncate_large_output(self):
        """Test that large outputs are truncated."""
        # Create output larger than MAX_TOOL_OUTPUT_SIZE
        large_output = {"data": "x" * (MAX_TOOL_OUTPUT_SIZE + 1000)}
        result = truncate_tool_output(large_output)
        
        self.assertIsInstance(result, dict)
        self.assertTrue(result.get("truncated"))
        self.assertIn("preview", result)
        self.assertIn("size", result)

    def test_truncate_string_output(self):
        """Test truncation of string output."""
        large_string = "x" * (MAX_TOOL_OUTPUT_SIZE + 1000)
        result = truncate_tool_output(large_string)
        
        self.assertIsInstance(result, dict)
        self.assertTrue(result.get("truncated"))

    def test_truncate_serialization_error(self):
        """Test handling of serialization errors."""
        # Create object that can't be serialized
        class Unserializable:
            def __str__(self):
                raise Exception("Cannot serialize")
        
        output = Unserializable()
        result = truncate_tool_output(output)
        
        self.assertIsInstance(result, dict)
        self.assertIn("error", result)


class TestLoadMessagesTask(TestCase):
    """Test load_messages_task function."""

    @patch('app.agents.functional.tasks.common.get_messages')
    def test_load_from_checkpoint(self, mock_get_messages):
        """Test loading messages from checkpoint."""
        # Setup mock checkpointer
        mock_checkpointer = Mock()
        mock_checkpoint = {
            "messages": [
                HumanMessage(content="Hello"),
                AIMessage(content="Hi there")
            ]
        }
        mock_checkpointer.get.return_value = mock_checkpoint
        
        # Test
        test_entrypoint = create_test_entrypoint(load_messages_task)
        result = test_entrypoint.invoke((1, mock_checkpointer, "thread-1"), config=get_test_config())
        
        # Verify
        self.assertEqual(len(result), 2)
        mock_checkpointer.get.assert_called_once()

    @patch('app.agents.functional.tasks.common.get_messages')
    def test_load_from_database_fallback(self, mock_get_messages):
        """Test fallback to database when checkpoint fails."""
        # Setup mock checkpointer to fail
        mock_checkpointer = Mock()
        mock_checkpointer.get.side_effect = Exception("Checkpoint error")
        
        # Setup mock database messages
        from app.db.models.message import Message
        mock_message = Mock(spec=Message)
        mock_message.role = "user"
        mock_message.content = "Hello"
        mock_message.metadata = None
        mock_get_messages.return_value = [mock_message]
        
        # Test
        test_entrypoint = create_test_entrypoint(load_messages_task)
        result = test_entrypoint.invoke((1, mock_checkpointer, "thread-1"), config=get_test_config())
        
        # Verify fallback to database
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], HumanMessage)
        mock_get_messages.assert_called_once_with(1)

    @patch('app.agents.functional.tasks.common.get_messages')
    def test_load_empty_messages(self, mock_get_messages):
        """Test loading when no messages exist."""
        mock_checkpointer = Mock()
        mock_checkpointer.get.return_value = None
        
        mock_get_messages.return_value = []
        
        # Test
        test_entrypoint = create_test_entrypoint(load_messages_task)
        result = test_entrypoint.invoke((1, mock_checkpointer, "thread-1"), config=get_test_config())
        
        # Verify empty result
        self.assertEqual(len(result), 0)

    @patch('app.agents.functional.tasks.common.get_messages')
    def test_load_assistant_message_with_metadata(self, mock_get_messages):
        """Test loading assistant message with metadata."""
        mock_checkpointer = Mock()
        mock_checkpointer.get.return_value = None
        
        from app.db.models.message import Message
        mock_message = Mock(spec=Message)
        mock_message.role = "assistant"
        mock_message.content = "Response"
        mock_message.metadata = {"agent_name": "greeter"}
        mock_get_messages.return_value = [mock_message]
        
        # Test
        test_entrypoint = create_test_entrypoint(load_messages_task)
        result = test_entrypoint.invoke((1, mock_checkpointer, "thread-1"), config=get_test_config())
        
        # Verify metadata is preserved
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], AIMessage)
        self.assertEqual(result[0].response_metadata, {"agent_name": "greeter"})


class TestCheckSummarizationNeededTask(TestCase):
    """Test check_summarization_needed_task function."""

    @patch('app.agents.functional.tasks.common.count_tokens')
    def test_summarization_not_needed(self, mock_count_tokens):
        """Test when summarization is not needed."""
        mock_count_tokens.return_value = 1000
        
        messages = [
            HumanMessage(content="Short message"),
            AIMessage(content="Short response")
        ]
        
        test_entrypoint = create_test_entrypoint(check_summarization_needed_task)
        result = test_entrypoint.invoke((messages, 40000, None), config=get_test_config())
        
        self.assertFalse(result)

    @patch('app.agents.functional.tasks.common.count_tokens')
    def test_summarization_needed(self, mock_count_tokens):
        """Test when summarization is needed."""
        mock_count_tokens.return_value = 20000
        
        messages = [
            HumanMessage(content="Long message"),
            AIMessage(content="Long response")
        ]
        
        test_entrypoint = create_test_entrypoint(check_summarization_needed_task)
        result = test_entrypoint.invoke({
            "messages": messages,
            "token_threshold": 30000
        }, config=get_test_config())
        
        self.assertTrue(result)

    @patch('app.agents.functional.tasks.common.count_tokens')
    def test_summarization_exact_threshold(self, mock_count_tokens):
        """Test when token count exactly matches threshold."""
        mock_count_tokens.return_value = 40000
        
        messages = [HumanMessage(content="Message")]
        
        test_entrypoint = create_test_entrypoint(check_summarization_needed_task)
        result = test_entrypoint.invoke((messages, 40000, None), config=get_test_config())
        
        self.assertTrue(result)

    @patch('app.agents.functional.tasks.common.count_tokens')
    def test_summarization_error_handling(self, mock_count_tokens):
        """Test error handling in summarization check."""
        mock_count_tokens.side_effect = Exception("Token counting failed")
        
        messages = [HumanMessage(content="Message")]
        
        test_entrypoint = create_test_entrypoint(check_summarization_needed_task)
        result = test_entrypoint.invoke((messages, 40000, None), config=get_test_config())
        
        # Should return False on error
        self.assertFalse(result)


class TestSaveMessageTask(TestCase):
    """Test save_message_task function."""

    @patch('app.services.chat_service.add_message')
    @patch('app.agents.functional.tasks.common.ChatSession')
    def test_save_new_message(self, mock_session_class, mock_add_message):
        """Test saving a new message."""
        # Setup mock session
        mock_session = Mock()
        mock_session.model_used = None
        mock_session.save = Mock()
        mock_session_class.objects.get.return_value = mock_session
        
        # Setup mock add_message
        mock_message = Mock()
        mock_message.id = 1
        mock_add_message.return_value = mock_message
        
        # Test
        response = AgentResponse(
            type="answer",
            reply="Hello",
            agent_name="greeter",
            token_usage={"input_tokens": 100, "output_tokens": 50, "total_tokens": 150}
        )
        
        test_entrypoint = create_test_entrypoint(save_message_task)
        # Note: @entrypoint functions need to be called with a dict for keyword args
        result = test_entrypoint.invoke({
            "response": response,
            "session_id": 1,
            "user_id": 1,
            "tool_calls": [],
            "run_id": "run-123",
            "parent_message_id": None
        }, config=get_test_config())
        
        # Verify
        self.assertTrue(result)
        mock_add_message.assert_called_once()
        mock_session.save.assert_called_once()

    @patch('app.db.models.message.Message')
    @patch('app.services.chat_service.add_message')
    @patch('app.agents.functional.tasks.common.ChatSession')
    def test_update_existing_message(self, mock_session_class, mock_add_message, mock_message_class):
        """Test updating existing message with same run_id."""
        # Setup mock session
        mock_session = Mock()
        mock_session.model_used = "gpt-4o-mini"
        mock_session_class.objects.get.return_value = mock_session
        
        # Setup existing message
        mock_existing_message = Mock()
        mock_existing_message.id = 1
        mock_existing_message.content = "Old content"
        mock_existing_message.tokens_used = 100
        mock_existing_message.metadata = {}
        mock_existing_message.save = Mock()
        
        mock_message_class.objects.filter.return_value.order_by.return_value.first.return_value = mock_existing_message
        
        # Test
        response = AgentResponse(
            type="answer",
            reply="Updated content",
            agent_name="greeter",
            token_usage={"total_tokens": 200}
        )
        
        test_entrypoint = create_test_entrypoint(save_message_task)
        result = test_entrypoint.invoke({
            "response": response,
            "session_id": 1,
            "user_id": 1,
            "run_id": "run-123"
        }, config=get_test_config())
        
        # Verify update
        self.assertTrue(result)
        self.assertEqual(mock_existing_message.content, "Updated content")
        mock_existing_message.save.assert_called_once()

    @patch('app.services.chat_service.add_message')
    @patch('app.agents.functional.tasks.common.ChatSession')
    def test_save_message_with_tool_calls(self, mock_session_class, mock_add_message):
        """Test saving message with tool calls."""
        # Setup mocks
        mock_session = Mock()
        mock_session.model_used = None
        mock_session.save = Mock()
        mock_session_class.objects.get.return_value = mock_session
        
        mock_message = Mock()
        mock_message.id = 1
        mock_add_message.return_value = mock_message
        
        # Test
        tool_calls = [
            {
                "name": "rag_retrieval_tool",
                "args": {"query": "test"},
                "status": "completed",
                "output": "Result"
            }
        ]
        
        response = AgentResponse(
            type="answer",
            reply="Hello",
            agent_name="search",
            tool_calls=tool_calls
        )
        
        test_entrypoint = create_test_entrypoint(save_message_task)
        result = test_entrypoint.invoke({
            "response": response,
            "session_id": 1,
            "user_id": 1,
            "tool_calls": tool_calls
        }, config=get_test_config())
        
        # Verify tool calls in metadata
        call_args = mock_add_message.call_args
        metadata = call_args[1]['metadata']
        self.assertEqual(len(metadata['tool_calls']), 1)
        self.assertEqual(metadata['tool_calls'][0]['name'], "rag_retrieval_tool")

    @patch('app.services.chat_service.add_message')
    @patch('app.agents.functional.tasks.common.ChatSession')
    def test_save_plan_proposal(self, mock_session_class, mock_add_message):
        """Test saving plan proposal message."""
        # Setup mocks
        mock_session = Mock()
        mock_session.model_used = None
        mock_session.save = Mock()
        mock_session_class.objects.get.return_value = mock_session
        
        mock_message = Mock()
        mock_message.id = 1
        mock_add_message.return_value = mock_message
        
        # Test
        response = AgentResponse(
            type="plan_proposal",
            plan={
                "type": "plan_proposal",
                "plan": [{"action": "tool", "tool": "test"}],
                "plan_index": 0,
                "plan_total": 1
            },
            agent_name="planner"
        )
        
        test_entrypoint = create_test_entrypoint(save_message_task)
        result = test_entrypoint.invoke({
            "response": response,
            "session_id": 1,
            "user_id": 1
        }, config=get_test_config())
        
        # Verify plan in metadata
        call_args = mock_add_message.call_args
        metadata = call_args[1]['metadata']
        self.assertEqual(metadata['response_type'], "plan_proposal")
        self.assertIn("plan", metadata)

    @patch('app.agents.functional.tasks.common.ChatSession')
    def test_save_message_error_handling(self, mock_session_class):
        """Test error handling when saving message."""
        # Setup mock to raise exception
        mock_session_class.objects.get.side_effect = Exception("Database error")
        
        response = AgentResponse(
            type="answer",
            reply="Hello",
            agent_name="greeter"
        )
        
        test_entrypoint = create_test_entrypoint(save_message_task)
        result = test_entrypoint.invoke({
            "response": response,
            "session_id": 1,
            "user_id": 1
        }, config=get_test_config())
        
        # Should return False on error
        self.assertFalse(result)
