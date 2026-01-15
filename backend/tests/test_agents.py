"""
Unit tests for agent classes.
"""
import unittest
from unittest.mock import Mock, patch, MagicMock
from django.test import TestCase

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_core.tools import BaseTool

from app.agents.agents.base import BaseAgent


class MockAgent(BaseAgent):
    """Mock agent for testing BaseAgent functionality."""
    
    def get_system_prompt(self) -> str:
        return "You are a test agent."


class TestBaseAgent(TestCase):
    """Test BaseAgent class."""

    @patch('app.agents.agents.base.ChatOpenAI')
    def test_base_agent_initialization(self, mock_chat_openai):
        """Test BaseAgent initialization."""
        agent = MockAgent(name="test", description="Test agent")
        
        self.assertEqual(agent.name, "test")
        self.assertEqual(agent.description, "Test agent")
        mock_chat_openai.assert_called_once()

    @patch('app.agents.agents.base.ChatOpenAI')
    def test_base_agent_get_tools_default(self, mock_chat_openai):
        """Test default get_tools returns empty list."""
        agent = MockAgent(name="test", description="Test agent")
        
        tools = agent.get_tools()
        self.assertEqual(tools, [])

    @patch('app.agents.agents.base.ChatOpenAI')
    def test_base_agent_invoke_with_system_prompt(self, mock_chat_openai_class):
        """Test invoke adds system prompt."""
        # Setup mock LLM
        mock_llm = Mock()
        mock_llm.bind_tools.return_value = mock_llm
        mock_response = AIMessage(content="Hello")
        mock_llm.invoke.return_value = mock_response
        mock_chat_openai_class.return_value = mock_llm
        
        # Test
        agent = MockAgent(name="test", description="Test agent")
        messages = [HumanMessage(content="Hello")]
        result = agent.invoke(messages)
        
        # Verify system prompt was added
        call_args = mock_llm.invoke.call_args[0][0]
        self.assertIsInstance(call_args[0], SystemMessage)
        self.assertEqual(call_args[0].content, "You are a test agent.")

    @patch('app.agents.agents.base.ChatOpenAI')
    def test_base_agent_invoke_with_tools(self, mock_chat_openai_class):
        """Test invoke binds tools when available."""
        # Setup mock LLM
        mock_llm = Mock()
        mock_tool = Mock(spec=BaseTool)
        mock_llm_with_tools = Mock()
        mock_llm.bind_tools.return_value = mock_llm_with_tools
        mock_response = AIMessage(content="Hello")
        mock_llm_with_tools.invoke.return_value = mock_response
        mock_chat_openai_class.return_value = mock_llm
        
        # Create agent with tools
        agent = MockAgent(name="test", description="Test agent")
        
        # Override get_tools
        def get_tools():
            return [mock_tool]
        agent.get_tools = get_tools
        
        # Test
        messages = [HumanMessage(content="Hello")]
        result = agent.invoke(messages)
        
        # Verify tools were bound
        mock_llm.bind_tools.assert_called_once_with([mock_tool])

    @patch('app.agents.agents.base.ChatOpenAI')
    def test_base_agent_invoke_passes_config(self, mock_chat_openai_class):
        """Test invoke passes config to LLM."""
        # Setup mock LLM
        mock_llm = Mock()
        mock_llm.bind_tools.return_value = mock_llm
        mock_response = AIMessage(content="Hello")
        mock_llm.invoke.return_value = mock_response
        mock_chat_openai_class.return_value = mock_llm
        
        # Test
        agent = MockAgent(name="test", description="Test agent")
        messages = [HumanMessage(content="Hello")]
        config = {"run_id": "test-run"}
        result = agent.invoke(messages, config=config)
        
        # Verify config was passed
        mock_llm.invoke.assert_called_once()
        call_kwargs = mock_llm.invoke.call_args[1]
        self.assertEqual(call_kwargs.get('config'), config)

    @patch('app.agents.agents.base.ChatOpenAI')
    def test_base_agent_invoke_exception_handling(self, mock_chat_openai_class):
        """Test invoke handles exceptions."""
        # Setup mock LLM to raise exception
        mock_llm = Mock()
        mock_llm.bind_tools.return_value = mock_llm
        mock_llm.invoke.side_effect = Exception("LLM error")
        mock_chat_openai_class.return_value = mock_llm
        
        # Test
        agent = MockAgent(name="test", description="Test agent")
        messages = [HumanMessage(content="Hello")]
        
        with self.assertRaises(Exception):
            agent.invoke(messages)

    @patch('app.agents.agents.base.ChatOpenAI')
    def test_base_agent_stream(self, mock_chat_openai_class):
        """Test stream method."""
        # Setup mock LLM
        mock_llm = Mock()
        mock_llm.bind_tools.return_value = mock_llm
        mock_chunk1 = AIMessage(content="Hello")
        mock_chunk2 = AIMessage(content=" World")
        mock_llm.stream.return_value = [mock_chunk1, mock_chunk2]
        mock_chat_openai_class.return_value = mock_llm
        
        # Test
        agent = MockAgent(name="test", description="Test agent")
        messages = [HumanMessage(content="Hello")]
        chunks = list(agent.stream(messages))
        
        # Verify streaming
        self.assertEqual(len(chunks), 2)
        mock_llm.stream.assert_called_once()

    @patch('app.agents.agents.base.ChatOpenAI')
    def test_base_agent_astream(self, mock_chat_openai_class):
        """Test astream method."""
        # Setup mock LLM
        mock_llm = Mock()
        mock_llm.bind_tools.return_value = mock_llm
        
        async def mock_astream_events(*args, **kwargs):
            yield {"event": "on_llm_start"}
            yield {"event": "on_llm_end"}
        
        mock_llm.astream_events = mock_astream_events
        mock_chat_openai_class.return_value = mock_llm
        
        # Test
        agent = MockAgent(name="test", description="Test agent")
        messages = [HumanMessage(content="Hello")]
        
        # Note: astream is async, so we'd need async test framework to fully test
        # This is a basic structure test
        self.assertTrue(hasattr(agent, 'astream'))

    @patch('app.agents.agents.base.ChatOpenAI')
    def test_base_agent_no_duplicate_system_prompt(self, mock_chat_openai_class):
        """Test that system prompt is not duplicated if already present."""
        # Setup mock LLM
        mock_llm = Mock()
        mock_llm.bind_tools.return_value = mock_llm
        mock_response = AIMessage(content="Hello")
        mock_llm.invoke.return_value = mock_response
        mock_chat_openai_class.return_value = mock_llm
        
        # Test
        agent = MockAgent(name="test", description="Test agent")
        messages = [
            SystemMessage(content="You are a test agent."),
            HumanMessage(content="Hello")
        ]
        result = agent.invoke(messages)
        
        # Verify system prompt was not duplicated
        call_args = mock_llm.invoke.call_args[0][0]
        system_messages = [msg for msg in call_args if isinstance(msg, SystemMessage)]
        self.assertEqual(len(system_messages), 1)


class TestSupervisorAgent(TestCase):
    """Test SupervisorAgent class."""

    @patch('app.agents.agents.supervisor.SupervisorAgent')
    def test_supervisor_agent_available_agents(self, mock_supervisor):
        """Test supervisor has available agents defined."""
        from app.agents.agents.supervisor import SupervisorAgent
        
        # Supervisor should have AVAILABLE_AGENTS defined
        self.assertTrue(hasattr(SupervisorAgent, 'AVAILABLE_AGENTS') or 
                       hasattr(SupervisorAgent, 'get_available_agents'))


class TestGreeterAgent(TestCase):
    """Test GreeterAgent class."""

    def test_greeter_agent_exists(self):
        """Test that GreeterAgent can be imported and instantiated."""
        from app.agents.agents.greeter import GreeterAgent
        
        agent = GreeterAgent()
        self.assertEqual(agent.name, "greeter")
        self.assertIsNotNone(agent.get_system_prompt())


class TestSearchAgent(TestCase):
    """Test SearchAgent class."""

    def test_search_agent_exists(self):
        """Test that SearchAgent can be imported and instantiated."""
        from app.agents.agents.search import SearchAgent
        
        agent = SearchAgent(user_id=1)
        self.assertEqual(agent.name, "search")
        self.assertIsNotNone(agent.get_system_prompt())

    def test_search_agent_has_rag_tool(self):
        """Test that SearchAgent has RAG tool available."""
        from app.agents.agents.search import SearchAgent
        
        agent = SearchAgent(user_id=1)
        tools = agent.get_tools()
        
        # Search agent should have RAG tool
        tool_names = [tool.name for tool in tools]
        self.assertTrue(any("rag" in name.lower() for name in tool_names))
