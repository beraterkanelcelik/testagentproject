"""
Routing logic for agent graph.
"""
from typing import Literal
from app.agents.graphs.state import AgentState
from app.agents.agents.supervisor import SupervisorAgent
from app.db.models.session import ChatSession
from app.db.models.message import Message


supervisor = SupervisorAgent()


def route_message(state: AgentState) -> Literal["greeter", "agent", "end"]:
    """
    Route message to appropriate agent based on supervisor decision.
    
    Args:
        state: Current graph state
        
    Returns:
        Next node to route to
    """
    # Get messages from state
    messages = state.get("messages", [])
    
    if not messages:
        return "end"
    
    # Check if this is the first message in the session
    chat_session_id = state.get("chat_session_id")
    if chat_session_id:
        try:
            session = ChatSession.objects.get(id=chat_session_id)
            message_count = Message.objects.filter(session=session).count()
            
            # First message in session -> greeter
            if message_count <= 1:  # User message + potential assistant response
                return "greeter"
        except ChatSession.DoesNotExist:
            pass
    
    # Use supervisor to determine routing
    try:
        agent_name = supervisor.route_message(messages)
        logger.debug(f"Supervisor routed to agent: {agent_name}")
        
        if agent_name == "greeter":
            return "greeter"
        else:
            # For now, route other agents to generic agent node
            # In future, we can have specific nodes for each agent
            state["next_agent"] = agent_name
            return "agent"
    except Exception as e:
        logger.error(f"Error in route_message: {e}", exc_info=True)
        # On error, default to greeter
        return "greeter"
