"""
Unit tests for Pydantic models.
"""
from django.test import TestCase
from pydantic import ValidationError

from app.agents.functional.models import (
    AgentRequest,
    AgentResponse,
    ToolProposal,
    RoutingDecision,
    ToolResult,
)


class TestAgentRequest(TestCase):
    """Test AgentRequest model."""

    def test_agent_request_minimal(self):
        """Test minimal AgentRequest."""
        request = AgentRequest(query="Hello")
        
        self.assertEqual(request.query, "Hello")
        self.assertIsNone(request.session_id)
        self.assertIsNone(request.user_id)
        self.assertEqual(request.flow, "main")

    def test_agent_request_full(self):
        """Test AgentRequest with all fields."""
        request = AgentRequest(
            query="Hello",
            session_id=1,
            user_id=2,
            flow="plan",
            plan_steps=[{"action": "tool", "tool": "test"}],
            trace_id="trace-123",
            run_id="run-456",
            parent_message_id=10
        )
        
        self.assertEqual(request.query, "Hello")
        self.assertEqual(request.session_id, 1)
        self.assertEqual(request.user_id, 2)
        self.assertEqual(request.flow, "plan")
        self.assertEqual(len(request.plan_steps), 1)
        self.assertEqual(request.trace_id, "trace-123")
        self.assertEqual(request.run_id, "run-456")
        self.assertEqual(request.parent_message_id, 10)

    def test_agent_request_missing_query(self):
        """Test AgentRequest validation requires query."""
        with self.assertRaises(ValidationError):
            AgentRequest()

    def test_agent_request_default_values(self):
        """Test AgentRequest default values."""
        request = AgentRequest(query="test")
        
        self.assertEqual(request.flow, "main")
        self.assertEqual(request.org_roles, [])
        self.assertEqual(request.app_roles, [])


class TestAgentResponse(TestCase):
    """Test AgentResponse model."""

    def test_agent_response_minimal(self):
        """Test minimal AgentResponse."""
        response = AgentResponse()
        
        self.assertEqual(response.type, "answer")
        self.assertIsNone(response.reply)
        self.assertEqual(response.tool_calls, [])

    def test_agent_response_full(self):
        """Test AgentResponse with all fields."""
        response = AgentResponse(
            type="answer",
            reply="Hello world",
            tool_calls=[{"name": "test_tool", "args": {}}],
            token_usage={"input_tokens": 100, "output_tokens": 50},
            agent_name="greeter",
            clarification="Need more info",
            context_usage={"total_tokens": 150}
        )
        
        self.assertEqual(response.reply, "Hello world")
        self.assertEqual(len(response.tool_calls), 1)
        self.assertEqual(response.agent_name, "greeter")

    def test_agent_response_plan_proposal(self):
        """Test AgentResponse with plan proposal."""
        response = AgentResponse(
            type="plan_proposal",
            plan={
                "type": "plan_proposal",
                "plan": [{"action": "tool", "tool": "test"}],
                "plan_index": 0,
                "plan_total": 1
            }
        )
        
        self.assertEqual(response.type, "plan_proposal")
        self.assertIsNotNone(response.plan)

    def test_agent_response_invalid_type(self):
        """Test AgentResponse with invalid type."""
        with self.assertRaises(ValidationError):
            AgentResponse(type="invalid_type")


class TestToolProposal(TestCase):
    """Test ToolProposal model."""

    def test_tool_proposal_minimal(self):
        """Test minimal ToolProposal."""
        proposal = ToolProposal(tool="test_tool", props={})
        
        self.assertEqual(proposal.tool, "test_tool")
        self.assertEqual(proposal.props, {})
        self.assertEqual(proposal.query, "")

    def test_tool_proposal_full(self):
        """Test ToolProposal with all fields."""
        proposal = ToolProposal(
            tool="rag_retrieval_tool",
            props={"query": "test query", "limit": 5},
            query="Search for documents"
        )
        
        self.assertEqual(proposal.tool, "rag_retrieval_tool")
        self.assertEqual(proposal.props["query"], "test query")
        self.assertEqual(proposal.query, "Search for documents")

    def test_tool_proposal_missing_required(self):
        """Test ToolProposal validation requires tool and props."""
        with self.assertRaises(ValidationError):
            ToolProposal()


class TestRoutingDecision(TestCase):
    """Test RoutingDecision model."""

    def test_routing_decision_minimal(self):
        """Test minimal RoutingDecision."""
        decision = RoutingDecision(agent="greeter", query="Hello")
        
        self.assertEqual(decision.agent, "greeter")
        self.assertEqual(decision.query, "Hello")
        self.assertFalse(decision.require_clarification)

    def test_routing_decision_full(self):
        """Test RoutingDecision with all fields."""
        decision = RoutingDecision(
            agent="search",
            query="Search for documents",
            require_clarification=True,
            confidence=0.95,
            reasoning="User wants to search",
            clarification_question="What should I search for?"
        )
        
        self.assertEqual(decision.agent, "search")
        self.assertTrue(decision.require_clarification)
        self.assertEqual(decision.confidence, 0.95)

    def test_routing_decision_invalid_agent(self):
        """Test RoutingDecision with invalid agent."""
        with self.assertRaises(ValidationError):
            RoutingDecision(agent="invalid_agent", query="test")

    def test_routing_decision_valid_agents(self):
        """Test RoutingDecision with all valid agents."""
        valid_agents = ["greeter", "gmail", "config", "search", "process"]
        
        for agent in valid_agents:
            decision = RoutingDecision(agent=agent, query="test")
            self.assertEqual(decision.agent, agent)


class TestToolResult(TestCase):
    """Test ToolResult model."""

    def test_tool_result_success(self):
        """Test ToolResult for successful execution."""
        result = ToolResult(
            tool="rag_retrieval_tool",
            args={"query": "test"},
            output="Found 5 documents",
            tool_call_id="call-123"
        )
        
        self.assertEqual(result.tool, "rag_retrieval_tool")
        self.assertEqual(result.output, "Found 5 documents")
        self.assertEqual(result.error, "")
        self.assertEqual(result.tool_call_id, "call-123")

    def test_tool_result_error(self):
        """Test ToolResult for failed execution."""
        result = ToolResult(
            tool="rag_retrieval_tool",
            args={"query": "test"},
            output=None,
            error="Tool execution failed",
            tool_call_id="call-123"
        )
        
        self.assertEqual(result.error, "Tool execution failed")
        self.assertIsNone(result.output)

    def test_tool_result_minimal(self):
        """Test ToolResult with minimal fields."""
        result = ToolResult(
            tool="test_tool",
            args={},
            output="result"
        )
        
        self.assertEqual(result.tool, "test_tool")
        self.assertEqual(result.error, "")
        self.assertIsNone(result.tool_call_id)

    def test_tool_result_missing_required(self):
        """Test ToolResult validation requires tool, args, and output."""
        with self.assertRaises(ValidationError):
            ToolResult()
