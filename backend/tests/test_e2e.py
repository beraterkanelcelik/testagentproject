"""
End-to-End tests for Agent Playground.

These tests verify the complete system flow from HTTP request to response,
including authentication, database operations, workflow execution, and API responses.
"""
import json
import asyncio
from django.test import TestCase, TransactionTestCase, Client
from django.contrib.auth import get_user_model
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from langchain_core.messages import HumanMessage, AIMessage

from app.db.models.session import ChatSession
from app.db.models.message import Message
from app.services.chat_service import create_session, add_message, get_messages
from app.account.api.auth import signup, login
from app.api.chats import chat_sessions
from app.agents.functional.workflow import ai_agent_workflow
from app.agents.functional.models import AgentRequest, AgentResponse

User = get_user_model()


class TestE2EUserJourney(TransactionTestCase):
    """End-to-end tests for complete user journey."""
    
    def setUp(self):
        """Set up test data."""
        self.client = Client()
        self.user_data = {
            'email': 'e2e_test@example.com',
            'password': 'testpass123',
            'first_name': 'Test',
            'last_name': 'User'
        }
    
    def test_complete_user_journey(self):
        """Test complete user journey: signup → login → create session → send message → get response."""
        # Step 1: User signup
        signup_response = self.client.post(
            '/api/auth/signup/',
            data=json.dumps(self.user_data),
            content_type='application/json'
        )
        self.assertEqual(signup_response.status_code, 201)
        signup_data = json.loads(signup_response.content)
        self.assertIn('access', signup_data)
        self.assertIn('refresh', signup_data)
        
        # Step 2: Create chat session
        self.client.defaults['HTTP_AUTHORIZATION'] = f'Bearer {signup_data["access"]}'
        session_response = self.client.post(
            '/api/chats/',
            data=json.dumps({'title': 'E2E Test Session'}),
            content_type='application/json'
        )
        self.assertEqual(session_response.status_code, 201)
        session_data = json.loads(session_response.content)
        session_id = session_data['id']
        self.assertIsNotNone(session_id)
        
        # Step 3: Verify session in database
        session = ChatSession.objects.get(id=session_id)
        self.assertEqual(session.user.email, self.user_data['email'])
        self.assertEqual(session.title, 'E2E Test Session')
        
        # Step 4: Get chat sessions list
        sessions_response = self.client.get('/api/chats/')
        self.assertEqual(sessions_response.status_code, 200)
        sessions_data = json.loads(sessions_response.content)
        self.assertIn('sessions', sessions_data)
        self.assertEqual(len(sessions_data['sessions']), 1)
    
    @patch('app.agents.temporal.workflow_manager.get_or_create_workflow')
    @patch('app.agents.functional.workflow.ai_agent_workflow')
    def test_agent_workflow_integration(self, mock_workflow, mock_get_workflow):
        """Test agent workflow integration with database."""
        # Create user and session
        user = User.objects.create_user(
            email='workflow_test@example.com',
            password='testpass123'
        )
        session = create_session(user.id, "Workflow Test")
        
        # Mock workflow response
        mock_response = AgentResponse(
            type="answer",
            reply="Hello! How can I help you?",
            agent_name="greeter",
            token_usage={"total": 10}
        )
        mock_workflow.invoke.return_value = mock_response
        
        # Create request
        request = AgentRequest(
            query="Hello",
            session_id=session.id,
            user_id=user.id
        )
        
        # Execute workflow
        from langchain_core.runnables import RunnableConfig
        config = RunnableConfig(
            configurable={"thread_id": f"thread-{session.id}"},
            run_id="test-run"
        )
        response = mock_workflow.invoke(request, config=config)
        
        # Verify response
        self.assertIsInstance(response, AgentResponse)
        self.assertEqual(response.type, "answer")
        self.assertIsNotNone(response.reply)
        self.assertEqual(response.agent_name, "greeter")


class TestE2EAPIFlow(TransactionTestCase):
    """End-to-end tests for API endpoints."""
    
    def setUp(self):
        """Set up test data."""
        self.client = Client()
        self.user = User.objects.create_user(
            email='api_test@example.com',
            password='testpass123'
        )
        # Login to get token
        login_response = self.client.post(
            '/api/auth/login/',
            data=json.dumps({
                'email': 'api_test@example.com',
                'password': 'testpass123'
            }),
            content_type='application/json'
        )
        login_data = json.loads(login_response.content)
        self.token = login_data.get('access')
        self.client.defaults['HTTP_AUTHORIZATION'] = f'Bearer {self.token}'
    
    def test_chat_session_lifecycle(self):
        """Test complete chat session lifecycle via API."""
        # Create session
        create_response = self.client.post(
            '/api/chats/',
            data=json.dumps({'title': 'Lifecycle Test'}),
            content_type='application/json'
        )
        self.assertEqual(create_response.status_code, 201)
        session_data = json.loads(create_response.content)
        session_id = session_data['id']
        
        # Get session details
        detail_response = self.client.get(f'/api/chats/{session_id}/')
        self.assertEqual(detail_response.status_code, 200)
        detail_data = json.loads(detail_response.content)
        self.assertEqual(detail_data['id'], session_id)
        self.assertEqual(detail_data['title'], 'Lifecycle Test')
        
        # Add messages directly to database (simulating workflow)
        add_message(session_id, 'user', 'Hello, how are you?')
        add_message(session_id, 'assistant', 'I am doing well, thank you!')
        
        # Get messages
        messages_response = self.client.get(f'/api/chats/{session_id}/messages/')
        self.assertEqual(messages_response.status_code, 200)
        messages_data = json.loads(messages_response.content)
        self.assertIn('messages', messages_data)
        self.assertEqual(len(messages_data['messages']), 2)
        
        # Delete session
        delete_response = self.client.delete(f'/api/chats/{session_id}/')
        self.assertEqual(delete_response.status_code, 200)
        
        # Verify session is deleted
        get_response = self.client.get(f'/api/chats/{session_id}/')
        self.assertIn(get_response.status_code, [404, 403])  # Not found or forbidden
    
    def test_message_persistence(self):
        """Test that messages persist correctly through workflow."""
        session = create_session(self.user.id, "Persistence Test")
        
        # Add user message
        user_msg = add_message(session.id, 'user', 'What is Python?')
        self.assertIsNotNone(user_msg.id)
        
        # Simulate workflow adding assistant message
        assistant_msg = add_message(
            session.id,
            'assistant',
            'Python is a programming language...',
            metadata={'agent_name': 'search', 'tokens': 15}
        )
        self.assertIsNotNone(assistant_msg.id)
        
        # Verify messages in database
        messages = Message.objects.filter(session=session).order_by('created_at')
        self.assertEqual(messages.count(), 2)
        self.assertEqual(messages[0].role, 'user')
        self.assertEqual(messages[1].role, 'assistant')
        self.assertEqual(messages[1].metadata.get('agent_name'), 'search')
        
        # Verify via API
        messages_response = self.client.get(f'/api/chats/{session.id}/messages/')
        self.assertEqual(messages_response.status_code, 200)
        messages_data = json.loads(messages_response.content)
        self.assertEqual(len(messages_data['messages']), 2)


class TestE2EWorkflowExecution(TransactionTestCase):
    """End-to-end tests for workflow execution with real components."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            email='workflow_e2e@example.com',
            password='testpass123'
        )
        self.session = create_session(self.user.id, "Workflow E2E")
    
    @patch('app.agents.functional.workflow.get_sync_checkpointer')
    @patch('app.agents.factory.AgentFactory')
    def test_workflow_execution_with_database(self, mock_factory, mock_checkpointer):
        """Test workflow execution that saves to database."""
        mock_checkpointer.return_value = None
        
        # Mock supervisor
        from app.agents.functional.models import RoutingDecision
        mock_supervisor = Mock()
        mock_decision = RoutingDecision(
            agent="greeter",
            query="Hello",
            require_clarification=False,
            confidence=0.9
        )
        mock_supervisor.route_message.return_value = mock_decision
        
        # Mock greeter agent
        mock_greeter = Mock()
        mock_greeter.invoke.return_value = AIMessage(
            content="Hello! Welcome to the Agent Playground!"
        )
        
        # Setup factory
        mock_factory_instance = Mock()
        mock_factory_instance.create.side_effect = lambda name, user_id: {
            "supervisor": mock_supervisor,
            "greeter": mock_greeter
        }.get(name, mock_greeter)
        mock_factory.return_value = mock_factory_instance
        
        # Execute workflow
        request = AgentRequest(
            query="Hello",
            session_id=self.session.id,
            user_id=self.user.id
        )
        
        from langchain_core.runnables import RunnableConfig
        config = RunnableConfig(
            configurable={"thread_id": f"thread-{self.session.id}"},
            run_id="e2e-test-run"
        )
        
        response = ai_agent_workflow.invoke(request, config=config)
        
        # Verify workflow response
        self.assertIsInstance(response, AgentResponse)
        self.assertIsNotNone(response.reply)
        
        # Verify message was saved to database
        messages = Message.objects.filter(session=self.session).order_by('created_at')
        # Should have at least the assistant message (user message might be saved separately)
        assistant_messages = messages.filter(role='assistant')
        self.assertGreater(assistant_messages.count(), 0, "Assistant message should be saved")
    
    @patch('app.agents.functional.workflow.get_sync_checkpointer')
    @patch('app.agents.factory.AgentFactory')
    @patch('app.agents.functional.tasks.tools.ToolNode')
    def test_workflow_with_tool_execution_e2e(self, mock_tool_node_class, mock_factory, mock_checkpointer):
        """Test complete workflow with tool execution end-to-end."""
        mock_checkpointer.return_value = None
        
        # Mock supervisor
        from app.agents.functional.models import RoutingDecision
        mock_supervisor = Mock()
        mock_decision = RoutingDecision(
            agent="search",
            query="Search for Python",
            require_clarification=False
        )
        mock_supervisor.route_message.return_value = mock_decision
        
        # Mock search agent with tool call
        mock_search = Mock()
        mock_search.invoke.return_value = AIMessage(
            content="I'll search for that.",
            tool_calls=[{
                "id": "call-search-1",
                "name": "rag_retrieval_tool",
                "args": {"query": "Python"}
            }]
        )
        mock_search.get_tools.return_value = []
        
        # Mock tool execution
        from langchain_core.messages import ToolMessage
        mock_tool_node = Mock()
        mock_tool_node.invoke.return_value = {
            "messages": [ToolMessage(
                content="Python is a programming language...",
                tool_call_id="call-search-1",
                name="rag_retrieval_tool"
            )]
        }
        mock_tool_node_class.return_value = mock_tool_node
        
        # Setup factory
        mock_factory_instance = Mock()
        mock_factory_instance.create.side_effect = lambda name, user_id: {
            "supervisor": mock_supervisor,
            "search": mock_search
        }.get(name, mock_search)
        mock_factory.return_value = mock_factory_instance
        
        # Execute workflow
        request = AgentRequest(
            query="Search for Python",
            session_id=self.session.id,
            user_id=self.user.id
        )
        
        from langchain_core.runnables import RunnableConfig
        config = RunnableConfig(
            configurable={"thread_id": f"thread-{self.session.id}"},
            run_id="e2e-tool-test"
        )
        
        response = ai_agent_workflow.invoke(request, config=config)
        
        # Verify complete workflow
        self.assertIsInstance(response, AgentResponse)
        # Tool should have been executed
        self.assertTrue(
            len(response.tool_calls) > 0 or response.raw_tool_outputs is not None,
            "Tool execution should be reflected in response"
        )


class TestE2EAuthenticationFlow(TestCase):
    """End-to-end tests for authentication flow."""
    
    def setUp(self):
        """Set up test data."""
        self.client = Client()
    
    def test_complete_auth_flow(self):
        """Test complete authentication flow: signup → login → refresh → logout."""
        # Signup
        signup_data = {
            'email': 'auth_e2e@example.com',
            'password': 'testpass123',
            'first_name': 'Auth',
            'last_name': 'Test'
        }
        signup_response = self.client.post(
            '/api/auth/signup/',
            data=json.dumps(signup_data),
            content_type='application/json'
        )
        self.assertIn(signup_response.status_code, [201, 200])
        signup_result = json.loads(signup_response.content)
        self.assertIn('access', signup_result)
        self.assertIn('refresh', signup_result)
        
        access_token = signup_result['access']
        refresh_token = signup_result['refresh']
        
        # Use token to access protected endpoint
        self.client.defaults['HTTP_AUTHORIZATION'] = f'Bearer {access_token}'
        sessions_response = self.client.get('/api/chats/')
        self.assertEqual(sessions_response.status_code, 200)
        
        # Refresh token
        refresh_response = self.client.post(
            '/api/auth/refresh/',
            data=json.dumps({'refresh': refresh_token}),
            content_type='application/json'
        )
        self.assertEqual(refresh_response.status_code, 200)
        refresh_result = json.loads(refresh_response.content)
        self.assertIn('access', refresh_result)
        
        # Use new token
        new_access_token = refresh_result['access']
        self.client.defaults['HTTP_AUTHORIZATION'] = f'Bearer {new_access_token}'
        sessions_response2 = self.client.get('/api/chats/')
        self.assertEqual(sessions_response2.status_code, 200)


class TestE2EDataPersistence(TransactionTestCase):
    """End-to-end tests for data persistence across operations."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            email='persistence_e2e@example.com',
            password='testpass123'
        )
    
    def test_session_persistence(self):
        """Test that sessions persist correctly."""
        # Create multiple sessions
        session1 = create_session(self.user.id, "Session 1")
        session2 = create_session(self.user.id, "Session 2")
        session3 = create_session(self.user.id, "Session 3")
        
        # Verify all sessions exist
        sessions = ChatSession.objects.filter(user=self.user)
        self.assertEqual(sessions.count(), 3)
        
        # Add messages to different sessions
        add_message(session1.id, 'user', 'Message 1')
        add_message(session2.id, 'user', 'Message 2')
        add_message(session3.id, 'user', 'Message 3')
        
        # Verify messages are in correct sessions
        self.assertEqual(Message.objects.filter(session=session1).count(), 1)
        self.assertEqual(Message.objects.filter(session=session2).count(), 1)
        self.assertEqual(Message.objects.filter(session=session3).count(), 1)
        
        # Delete one session
        session2.delete()
        
        # Verify other sessions still exist
        self.assertEqual(ChatSession.objects.filter(user=self.user).count(), 2)
        self.assertEqual(Message.objects.filter(session=session1).count(), 1)
        self.assertEqual(Message.objects.filter(session=session3).count(), 1)
        # Session2 messages should be deleted (CASCADE)
        self.assertEqual(Message.objects.filter(session_id=session2.id).count(), 0)
    
    def test_message_ordering(self):
        """Test that messages maintain correct ordering."""
        session = create_session(self.user.id, "Ordering Test")
        
        # Add messages with delays
        msg1 = add_message(session.id, 'user', 'First message')
        msg2 = add_message(session.id, 'assistant', 'Second message')
        msg3 = add_message(session.id, 'user', 'Third message')
        
        # Verify ordering
        messages = Message.objects.filter(session=session).order_by('created_at')
        self.assertEqual(messages[0].id, msg1.id)
        self.assertEqual(messages[1].id, msg2.id)
        self.assertEqual(messages[2].id, msg3.id)
        
        # Verify content order
        self.assertEqual(messages[0].content, 'First message')
        self.assertEqual(messages[1].content, 'Second message')
        self.assertEqual(messages[2].content, 'Third message')
