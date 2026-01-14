"""
Token context usage tracking for frontend display.

Provides utilities to calculate and track token usage as a percentage
of the model's context window, similar to coding agents.
"""
from typing import Dict, Any, List
from langchain_core.messages import BaseMessage
from app.agents.config import get_model_context_window, OPENAI_MODEL
from app.rag.chunking.tokenizer import count_tokens
from app.core.logging import get_logger

logger = get_logger(__name__)


def calculate_context_usage(
    messages: List[BaseMessage],
    model_name: str = None
) -> Dict[str, Any]:
    """
    Calculate token usage as percentage of context window.

    Args:
        messages: List of conversation messages
        model_name: Model name (defaults to OPENAI_MODEL)

    Returns:
        Dictionary with:
        - total_tokens: Total tokens in conversation
        - context_window: Model's context window size
        - usage_percentage: Percentage of context used
        - tokens_remaining: Tokens remaining in context
    """
    model_name = model_name or OPENAI_MODEL

    try:
        # Get model's context window size
        context_window = get_model_context_window(model_name)

        # Count tokens in all messages
        total_tokens = 0
        for message in messages:
            if hasattr(message, 'content') and message.content:
                content = str(message.content)
                tokens = count_tokens(content, model_name)
                total_tokens += tokens

        # Calculate percentage and remaining
        usage_percentage = (total_tokens / context_window) * 100 if context_window > 0 else 0
        tokens_remaining = max(0, context_window - total_tokens)

        result = {
            "total_tokens": total_tokens,
            "context_window": context_window,
            "usage_percentage": round(usage_percentage, 1),
            "tokens_remaining": tokens_remaining
        }

        logger.debug(
            f"Context usage: {total_tokens}/{context_window} tokens "
            f"({usage_percentage:.1f}%)"
        )

        return result

    except Exception as e:
        logger.error(f"Error calculating context usage: {e}", exc_info=True)
        # Return safe defaults on error
        return {
            "total_tokens": 0,
            "context_window": 128000,
            "usage_percentage": 0.0,
            "tokens_remaining": 128000
        }


def should_trigger_summarization(
    context_usage: Dict[str, Any],
    threshold_percentage: float = 80.0
) -> bool:
    """
    Check if context usage warrants summarization.

    Args:
        context_usage: Context usage dictionary from calculate_context_usage()
        threshold_percentage: Percentage threshold to trigger summarization

    Returns:
        True if summarization should be triggered
    """
    usage_percentage = context_usage.get("usage_percentage", 0)
    should_summarize = usage_percentage >= threshold_percentage

    if should_summarize:
        logger.info(
            f"Summarization triggered: {usage_percentage:.1f}% >= {threshold_percentage}%"
        )

    return should_summarize
