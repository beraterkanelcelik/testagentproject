"""
Pydantic models for Functional API request/response.
"""
from pydantic import BaseModel
from typing import List, Dict, Any, Optional, Literal


class AgentRequest(BaseModel):
    """Input request for the agent."""
    query: str
    session_id: Optional[int] = None
    org_slug: Optional[str] = None
    user_id: Optional[int] = None
    org_roles: List[str] = []
    app_roles: List[str] = []
    flow: str = "main"  # main, direct, plan
    plan_steps: Optional[List[Dict[str, Any]]] = None  # For plan execution
    trace_id: Optional[str] = None  # Langfuse trace ID for tracing


class ToolProposal(BaseModel):
    """Tool execution proposal."""
    tool: str
    props: Dict[str, Any]
    query: str = ""


class RoutingDecision(BaseModel):
    """Supervisor routing decision."""
    agent: Literal["greeter", "gmail", "config", "search", "process"]
    query: str
    require_clarification: bool = False


class ToolResult(BaseModel):
    """Tool execution result."""
    tool: str
    args: Dict[str, Any]
    output: Any
    error: str = ""


class AgentResponse(BaseModel):
    """Final agent response."""
    type: Literal["answer", "plan_proposal"] = "answer"
    reply: Optional[str] = None
    tool_calls: List[Dict[str, Any]] = []
    token_usage: Dict[str, int] = {}
    agent_name: Optional[str] = None
    clarification: Optional[str] = None
    plan: Optional[Dict[str, Any]] = None
    raw_tool_outputs: Optional[List[Dict[str, Any]]] = None
