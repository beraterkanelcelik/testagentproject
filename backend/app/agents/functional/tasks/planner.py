"""
Planning agent task for generating execution plans.

This module provides LangGraph task for analyzing queries and generating
structured plans for multi-step operations.
"""
import json
from typing import List, Dict, Any, Optional
from langgraph.func import task
from langchain_core.messages import BaseMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from app.core.logging import get_logger

logger = get_logger(__name__)

PLANNING_SYSTEM_PROMPT = """You are a planning agent that breaks down complex tasks into executable steps.

Given a user query, analyze if it requires multiple steps to complete. If so, generate a structured plan.

A task requires planning if it involves:
- Multiple tool calls (e.g., "search for X, then email the results")
- Sequential operations (e.g., "get data, analyze it, create report")
- Multi-part requests (e.g., "do A, B, and C")
- Operations that depend on previous results

For single-step tasks or simple queries, return {"requires_plan": false}.

For multi-step tasks, break them down into a sequence of actions. Each step should specify:
- action: "tool" (execute a tool) or "answer" (provide direct response)
- tool: tool name (if action=tool)
- props: tool arguments as JSON object
- agent: which agent should execute this step
- query: context/description for the agent

Output ONLY valid JSON in this exact format:
{
  "requires_plan": boolean,
  "reasoning": "Brief explanation of why planning is/isn't needed",
  "plan": [
    {
      "action": "tool",
      "tool": "search_documents",
      "props": {"query": "search query here"},
      "agent": "search",
      "query": "Search for relevant documents about X"
    },
    {
      "action": "answer",
      "answer": "Provide synthesis or final response",
      "agent": "greeter",
      "query": "Synthesize the results"
    }
  ]
}

Examples:

Simple query: "What is Python?"
Response: {"requires_plan": false, "reasoning": "Single step query - can be answered directly", "plan": []}

Multi-step query: "Search for Python tutorials, then email me the top 3 results"
Response: {
  "requires_plan": true,
  "reasoning": "Requires two sequential steps: search and email",
  "plan": [
    {
      "action": "tool",
      "tool": "search_documents",
      "props": {"query": "Python tutorials", "limit": 3},
      "agent": "search",
      "query": "Search for Python tutorials"
    },
    {
      "action": "tool",
      "tool": "send_email",
      "props": {"subject": "Top Python Tutorials", "body": "Results from search"},
      "agent": "gmail",
      "query": "Email the search results"
    }
  ]
}

Available agents: greeter (general), search (document search), gmail (email), process (system ops)
Available tools will depend on the agent - use common tool names like search_documents, send_email, etc.

Remember: Only output valid JSON, nothing else."""


@task
def analyze_and_plan(
    messages: List[BaseMessage],
    user_id: Optional[int] = None,
    config: Optional[RunnableConfig] = None
) -> Dict[str, Any]:
    """
    Analyze query and generate execution plan if needed.

    This task uses an LLM to determine if a query requires multi-step planning
    and generates a structured plan if necessary.

    Args:
        messages: Conversation history including the user query
        user_id: User ID for agent context
        config: LangGraph runtime configuration

    Returns:
        Dictionary with:
        - requires_plan (bool): Whether the query needs planning
        - reasoning (str): Explanation of the decision
        - plan (List[Dict]): List of execution steps (empty if no plan needed)
    """
    try:
        logger.info("[PLANNING] Starting plan analysis")

        # Get planning agent (uses Claude with structured output)
        from app.agents.factory import AgentFactory
        planning_agent = AgentFactory.create("planner", user_id=user_id)

        # Build planning messages with system prompt
        planning_messages = [
            SystemMessage(content=PLANNING_SYSTEM_PROMPT),
            *messages
        ]

        logger.debug(f"[PLANNING] Invoking planning agent with {len(messages)} messages")

        # Invoke agent to get plan
        response = planning_agent.invoke(planning_messages, config=config)

        # Parse structured output from response
        if hasattr(response, 'content'):
            content = response.content

            # Try to extract JSON from markdown code blocks if present
            if '```json' in content:
                content = content.split('```json')[1].split('```')[0].strip()
            elif '```' in content:
                content = content.split('```')[1].split('```')[0].strip()

            result = json.loads(content)
        else:
            # Response is already a dict
            result = response

        # Validate response structure
        if not isinstance(result, dict):
            logger.warning("[PLANNING] Response is not a dict, treating as no plan needed")
            return {"requires_plan": False, "reasoning": "Invalid response format", "plan": []}

        requires_plan = result.get('requires_plan', False)
        plan_steps = result.get('plan', [])
        reasoning = result.get('reasoning', '')

        logger.info(f"[PLANNING] Analysis complete: requires_plan={requires_plan}, steps={len(plan_steps)}")
        logger.debug(f"[PLANNING] Reasoning: {reasoning}")

        if requires_plan and plan_steps:
            logger.info(f"[PLANNING] Generated plan with {len(plan_steps)} steps")
            for idx, step in enumerate(plan_steps):
                action = step.get('action', 'unknown')
                tool = step.get('tool', step.get('answer', 'N/A'))
                logger.debug(f"[PLANNING] Step {idx + 1}: {action} - {tool}")

        return result

    except json.JSONDecodeError as e:
        logger.error(f"[PLANNING] Failed to parse JSON response: {e}", exc_info=True)
        return {
            "requires_plan": False,
            "reasoning": f"Failed to parse planning response: {str(e)}",
            "plan": []
        }
    except Exception as e:
        logger.error(f"[PLANNING] Error in planning agent: {e}", exc_info=True)
        return {
            "requires_plan": False,
            "reasoning": f"Planning failed: {str(e)}",
            "plan": []
        }
