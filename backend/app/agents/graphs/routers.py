"""
Routing logic for agent graph.
"""
from typing import Literal
from app.agents.graphs.state import AgentState
from app.agents.agents.supervisor import SupervisorAgent
from app.core.logging import get_logger

logger = get_logger(__name__)

supervisor = SupervisorAgent()


def route_message(state: AgentState, config: dict = None) -> Literal["greeter", "agent", "end"]:
    """
    Route message to appropriate agent based on supervisor decision.
    
    Args:
        state: Current graph state
        config: Optional runtime config (contains callbacks from graph.invoke())
        
    Returns:
        Next node to route to
    """
    # Get messages from state
    messages = state.get("messages", [])
    
    if not messages:
        return "end"
    
    try:
        # Use supervisor to determine routing
        # Pass config so callbacks propagate to supervisor's LLM call
        invoke_kwargs = {}
        if config:
            invoke_kwargs['config'] = config
        agent_name = supervisor.route_message(messages, **invoke_kwargs)
        logger.debug(f"Supervisor routed to agent: {agent_name}")
        
        if agent_name == "greeter":
            return "greeter"
        else:
            # Route other agents to generic agent node
            state["next_agent"] = agent_name
            return "agent"
    except Exception as e:
        logger.error(f"Error in route_message: {e}", exc_info=True)
        # On error, default to greeter
        return "greeter"
