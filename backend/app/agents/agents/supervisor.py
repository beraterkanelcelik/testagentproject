"""
Supervisor agent for routing messages to appropriate sub-agents.
"""
from typing import List, Optional, Literal
from pydantic import BaseModel, Field
from langchain_core.messages import BaseMessage, AIMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from app.agents.agents.base import BaseAgent
from app.core.logging import get_logger

logger = get_logger(__name__)


class RoutingDecisionModel(BaseModel):
    """Structured routing decision from supervisor."""
    agent: Literal["greeter", "search", "gmail", "config", "process"] = Field(
        description="The agent to route this query to"
    )
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="Confidence in routing decision (0-1)"
    )
    reasoning: str = Field(
        description="Brief explanation of why this agent was chosen"
    )
    requires_clarification: bool = Field(
        default=False,
        description="Whether clarification is needed before proceeding"
    )
    clarification_question: Optional[str] = Field(
        default=None,
        description="Question to ask user if clarification needed"
    )


class SupervisorAgent(BaseAgent):
    """
    Supervisor agent that routes user messages to appropriate sub-agents.
    """
    
    # Available agents - can be moved to config or registry in future
    AVAILABLE_AGENTS = {
        "greeter": "Provides welcome messages and guidance. Use when user needs help or is starting.",
        "search": "Searches through user's uploaded documents and answers questions using RAG. Use when user asks about their documents, wants to search for information, or asks questions that might be in their uploaded files.",
        "gmail": "Handles email-related tasks. Use when user asks about emails, messages, or mail.",
    }
    
    def __init__(self):
        super().__init__(
            name="supervisor",
            description="Routes user messages to appropriate sub-agents",
            temperature=0.0  # Deterministic routing
        )
        # Bind structured output for reliable parsing
        try:
            self.routing_llm = self.llm.with_structured_output(
                RoutingDecisionModel,
                method="function_calling"  # More reliable than JSON mode
            )
        except Exception as e:
            logger.warning(f"Failed to create structured output LLM: {e}, falling back to regular LLM")
            self.routing_llm = None
    
    def get_system_prompt(self) -> str:
        """Get system prompt for supervisor agent."""
        agents_list = "\n".join([
            f"- {name}: {desc}" 
            for name, desc in self.AVAILABLE_AGENTS.items()
        ])
        
        return f"""You are a supervisor agent that routes user messages to the appropriate sub-agent.

Available agents:
{agents_list}

Your task is to analyze the user's message and determine which agent should handle it.
Consider:
- User intent and what they're asking for
- Whether this is a first message or help request (→ greeter)
- Whether user wants to search documents or ask questions about their uploaded files (→ search)
- Questions about people, entities, facts, or information that might be in documents (→ search)
- "Who is X?", "What is X?", "Tell me about X" type questions (→ search)
- Whether it's email-related (→ gmail)
- If unclear, route to greeter for guidance

IMPORTANT: Questions asking about specific people, entities, or facts (e.g., "who is X?", "what is X?", "tell me about X") should be routed to the search agent, as they likely need to search through uploaded documents.

Provide your routing decision with confidence score and reasoning."""
    
    def route_message(
        self, 
        messages: List[BaseMessage],
        config: Optional[RunnableConfig] = None,
        **kwargs
    ) -> RoutingDecisionModel:
        """
        Route message with structured output parsing.
        
        Args:
            messages: Conversation messages
            config: Optional runtime config (for callbacks)
            **kwargs: Additional arguments
            
        Returns:
            RoutingDecisionModel with agent, confidence, reasoning, etc.
        """
        try:
            # Get the latest user message for keyword-based routing
            from langchain_core.messages import HumanMessage
            latest_message = None
            if messages:
                for msg in reversed(messages):
                    if isinstance(msg, HumanMessage) and hasattr(msg, 'content') and msg.content:
                        latest_message = msg.content.lower().strip()
                        break
            
            # Explicit keyword-based routing for common search queries
            if latest_message:
                search_keywords = [
                    "who is", "what is", "tell me about", "who are", "what are",
                    "search for", "find information about", "look up", "information about"
                ]
                if any(latest_message.startswith(keyword) for keyword in search_keywords):
                    logger.info(f"Keyword-based routing: routing '{latest_message[:50]}...' to search agent")
                    return RoutingDecisionModel(
                        agent="search",
                        confidence=1.0,
                        reasoning="Matched search keyword pattern",
                        requires_clarification=False
                    )
            
            # Use structured output if available
            if self.routing_llm:
                system = SystemMessage(content=self.get_system_prompt())
                invoke_kwargs = {}
                if config:
                    invoke_kwargs['config'] = config
                
                try:
                    decision = self.routing_llm.invoke(
                        [system] + messages,
                        **invoke_kwargs
                    )
                except Exception as e:
                    logger.warning(f"Structured output parsing failed: {e}, falling back to regular invoke")
                    decision = None
            else:
                decision = None
            
            # Fallback to regular invoke if structured output not available or failed
            if decision is None:
                system = SystemMessage(content=self.get_system_prompt())
                invoke_kwargs = {}
                if config:
                    invoke_kwargs['config'] = config
                
                response = self.invoke([system] + messages, **invoke_kwargs)
                
                # Extract agent name from response
                if not response or not hasattr(response, 'content') or not response.content:
                    logger.warning("Supervisor response is empty or invalid, defaulting to greeter")
                    return RoutingDecisionModel(
                        agent="greeter",
                        confidence=0.5,
                        reasoning="Fallback due to empty response",
                        requires_clarification=True,
                        clarification_question="I'm not sure I understood. Could you rephrase your request?"
                    )
                
                agent_name = response.content.strip().lower()
                
                # Validate agent name
                if agent_name not in self.AVAILABLE_AGENTS:
                    agent_name = "greeter"
                
                decision = RoutingDecisionModel(
                    agent=agent_name,
                    confidence=0.7,  # Default confidence for text-based routing
                    reasoning="Text-based routing from LLM response",
                    requires_clarification=False
                )
            
            # Auto-clarification for low confidence
            if decision.confidence < 0.7 and not decision.requires_clarification:
                decision.requires_clarification = True
                decision.clarification_question = (
                    f"I think you want to use the {decision.agent} agent, "
                    "but I'm not fully sure. Is that correct?"
                )
            
            logger.info(
                f"Supervisor routing decision: agent={decision.agent}, "
                f"confidence={decision.confidence:.2f}, "
                f"requires_clarification={decision.requires_clarification}"
            )
            
            return decision
            
        except Exception as e:
            logger.error(f"Error in supervisor route_message: {e}", exc_info=True)
            # Fallback to greeter on error
            return RoutingDecisionModel(
                agent="greeter",
                confidence=0.5,
                reasoning="Fallback due to routing error",
                requires_clarification=True,
                clarification_question="I'm not sure I understood. Could you rephrase your request?"
            )
    
    def get_tools(self) -> List:
        """Supervisor doesn't need tools."""
        return []
