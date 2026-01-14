"""
Pydantic schemas for API request validation.
"""
import re
from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any


class StreamAgentRequest(BaseModel):
    """Validated request for agent streaming."""
    
    chat_session_id: int = Field(..., gt=0, description="Chat session ID")
    message: str = Field(..., min_length=1, max_length=100000, description="User message")
    plan_steps: Optional[List[Dict[str, Any]]] = None
    flow: str = Field(default="main", pattern="^(main|plan)$", description="Flow type")
    idempotency_key: Optional[str] = Field(None, max_length=64, description="Idempotency key")
    
    @validator('message')
    def sanitize_message(cls, v):
        """Sanitize message content."""
        # Remove null bytes and control characters
        v = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', v)
        return v.strip()
    
    @validator('plan_steps')
    def validate_plan_steps(cls, v):
        """Validate plan steps."""
        if v is None:
            return v
        if len(v) > 20:
            raise ValueError("Too many plan steps (max 20)")
        # Validate each step has required fields
        for step in v:
            if not isinstance(step, dict):
                raise ValueError("Plan step must be a dictionary")
            if 'action' not in step:
                raise ValueError("Plan step must have 'action' field")
        return v


class RunAgentRequest(BaseModel):
    """Validated request for non-streaming agent execution."""
    
    chat_session_id: int = Field(..., gt=0)
    message: str = Field(..., min_length=1, max_length=100000)
    plan_steps: Optional[List[Dict[str, Any]]] = None
    flow: str = Field(default="main", pattern="^(main|plan)$")
    
    @validator('message')
    def sanitize_message(cls, v):
        """Sanitize message content."""
        v = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', v)
        return v.strip()
    
    @validator('plan_steps')
    def validate_plan_steps(cls, v):
        """Validate plan steps."""
        if v is None:
            return v
        if len(v) > 20:
            raise ValueError("Too many plan steps (max 20)")
        return v


class ToolApprovalRequest(BaseModel):
    """Validated request for tool approval."""
    
    tool_call_id: str = Field(..., min_length=1, max_length=64)
    approved: bool
    args: Optional[Dict[str, Any]] = None
    
    @validator('args')
    def validate_args(cls, v):
        """Validate tool arguments."""
        if v is not None:
            # Limit args size
            import json
            args_size = len(json.dumps(v, default=str))
            if args_size > 10000:  # 10KB limit
                raise ValueError(f"Tool args too large: {args_size} bytes")
        return v
