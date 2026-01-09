"""
Main LangGraph definition for supervisor-based multi-agent system.
"""
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.base import BaseCheckpointSaver
from app.agents.graphs.state import AgentState
from app.agents.graphs.nodes import supervisor_node, greeter_node, agent_node, tool_node
from app.agents.graphs.routers import route_message
from app.agents.checkpoint import get_checkpoint_saver
from app.core.logging import get_logger

logger = get_logger(__name__)


def create_agent_graph(checkpoint_saver: BaseCheckpointSaver = None) -> StateGraph:
    """
    Create and compile the agent graph.
    
    Args:
        checkpoint_saver: Optional checkpoint saver (uses default if None)
        
    Returns:
        Compiled StateGraph
    """
    # Create state graph
    graph = StateGraph(AgentState)
    
    # Add nodes
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("greeter", greeter_node)
    graph.add_node("agent", agent_node)
    graph.add_node("tool", tool_node)
    
    # Set entry point
    graph.set_entry_point("supervisor")
    
    # Add conditional edges from supervisor
    graph.add_conditional_edges(
        "supervisor",
        route_message,
        {
            "greeter": "greeter",
            "agent": "agent",
            "end": END,
        }
    )
    
    # Add edges from greeter and agent to end
    graph.add_edge("greeter", END)
    graph.add_edge("agent", END)
    
    # Add conditional edge from tool (can route back to agent or end)
    graph.add_edge("tool", END)
    
    # Compile with checkpoint if provided
    if checkpoint_saver:
        try:
            compiled_graph = graph.compile(checkpointer=checkpoint_saver)
            logger.debug("Graph compiled with checkpoint persistence")
        except Exception as e:
            logger.error(f"Failed to compile graph with checkpoint: {e}", exc_info=True)
            logger.warning("Falling back to graph without checkpoint")
            compiled_graph = graph.compile()
    else:
        compiled_graph = graph.compile()
        logger.debug("Graph compiled without checkpoint persistence")
    
    return compiled_graph
