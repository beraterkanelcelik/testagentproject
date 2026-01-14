"""
Tool execution tasks using LangGraph's ToolNode for LangGraph Functional API.
"""
from typing import List, Dict, Any, Optional
from langgraph.func import task
from langgraph.prebuilt import ToolNode
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from app.agents.functional.models import ToolResult
from app.agents.registry import get_agent
from app.core.logging import get_logger

logger = get_logger(__name__)


@task
def execute_tools(
    tool_calls: List[Dict[str, Any]],
    agent_name: str,
    user_id: int,
    config: Optional[RunnableConfig] = None
) -> List[ToolResult]:
    """
    Execute tools using LangGraph's ToolNode for automatic ID management.
    
    Args:
        tool_calls: List of tool call dictionaries with 'name', 'args', and 'id'
        agent_name: Name of agent that has the tools
        user_id: User ID for tool access
        config: Optional runtime config (for callbacks)
        
    Returns:
        List of ToolResult objects with tool_call_id automatically managed
    """
    try:
        logger.info(f"[EXECUTE_TOOLS] Starting execution of {len(tool_calls)} tools for agent={agent_name}")
        
        # Get agent for tools
        agent = get_agent(agent_name, user_id)
        tools = agent.get_tools()
        
        if not tools:
            logger.warning(f"No tools available for agent {agent_name}")
            return []
        
        # Use LangGraph's ToolNode for proper tool execution
        tool_node = ToolNode(tools)
        
        # Create AIMessage with tool_calls for ToolNode input
        ai_msg = AIMessage(content="", tool_calls=tool_calls)
        
        # ToolNode handles execution and returns ToolMessages with proper IDs
        import time
        start_time = time.time()
        try:
            # ToolNode doesn't need config for basic execution
            # Config is mainly for callbacks and checkpointing which aren't needed for tool execution
            # Passing malformed config causes "Missing required config key" errors
            result = tool_node.invoke({"messages": [ai_msg]})
            duration = time.time() - start_time
            
            # Record metrics for each tool
            for tc in tool_calls:
                tool_name = tc.get("name", "")
                try:
                    from app.observability.metrics import record_tool_call
                    record_tool_call(tool_name, duration, status="success")
                except Exception:
                    pass
        except Exception as e:
            duration = time.time() - start_time
            # Record error metrics
            for tc in tool_calls:
                tool_name = tc.get("name", "")
                try:
                    from app.observability.metrics import record_tool_call
                    record_tool_call(tool_name, duration, status="error")
                except Exception:
                    pass
            raise
        
        # Extract ToolMessages from result
        tool_messages = [msg for msg in result.get("messages", []) if isinstance(msg, ToolMessage)]
        
        # Convert to ToolResult format
        results = []
        for tool_msg in tool_messages:
            # Find matching tool call by ID
            matching_tool_call = None
            for tc in tool_calls:
                if tc.get("id") == tool_msg.tool_call_id:
                    matching_tool_call = tc
                    break
            
            results.append(ToolResult(
                tool=tool_msg.name,
                args=matching_tool_call.get("args", {}) if matching_tool_call else {},
                output=tool_msg.content,
                error="",
                tool_call_id=tool_msg.tool_call_id  # Automatically managed by ToolNode
            ))
        
        logger.info(f"[EXECUTE_TOOLS] Completed execution: {len(results)} results returned")
        return results
        
    except Exception as e:
        logger.error(f"[EXECUTE_TOOLS] Error executing tools: {e}", exc_info=True)
        # Return error results for all tool calls
        error_results = []
        for tc in tool_calls:
            error_results.append(ToolResult(
                tool=tc.get("name", ""),
                args=tc.get("args", {}),
                output=None,
                error=str(e),
                tool_call_id=tc.get("id")
            ))
        return error_results
