"""
Supervisor routing task for LangGraph Functional API.
"""
from typing import List, Optional
from langgraph.func import task
from langchain_core.messages import BaseMessage
from langchain_core.runnables import RunnableConfig
from app.agents.agents.supervisor import SupervisorAgent
from app.agents.functional.models import RoutingDecision
from app.core.logging import get_logger

logger = get_logger(__name__)


@task
def route_to_agent(
    messages: List[BaseMessage],
    config: Optional[RunnableConfig] = None
) -> RoutingDecision:
    """
    Route query to appropriate agent using structured output.
    
    Args:
        messages: Conversation history as LangChain messages
        config: Optional runtime config (for callbacks)
        
    Returns:
        RoutingDecision with agent name and query
    """
    try:
        supervisor = SupervisorAgent()
        
        invoke_kwargs = {}
        if config:
            invoke_kwargs['config'] = config
        
        # Get the latest user message for query extraction
        from langchain_core.messages import HumanMessage
        query = ""
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage) and hasattr(msg, 'content') and msg.content:
                query = str(msg.content)
                break
        
        # Route message - supervisor returns RoutingDecisionModel
        decision = supervisor.route_message(messages, config=config)
        
        # Convert RoutingDecisionModel to RoutingDecision (for backward compatibility)
        logger.debug(f"Supervisor routed to agent: {decision.agent}, confidence={decision.confidence:.2f}")
        return RoutingDecision(
            agent=decision.agent,
            query=query,
            require_clarification=decision.requires_clarification
        )
    except Exception as e:
        logger.error(f"Error in route_to_agent: {e}", exc_info=True)
        # Fallback to greeter
        from langchain_core.messages import HumanMessage
        query = ""
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage) and hasattr(msg, 'content') and msg.content:
                query = str(msg.content)
                break
        return RoutingDecision(agent="greeter", query=query)
