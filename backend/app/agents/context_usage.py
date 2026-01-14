"""
Token context usage tracking and message trimming for frontend display.

Provides utilities to calculate and track token usage as a percentage
of the model's context window, and trim messages using LangChain's built-in utilities.
"""
from typing import Dict, Any, List, Optional
from langchain_core.messages import BaseMessage, trim_messages, SystemMessage
from langchain_openai import ChatOpenAI
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


def get_trimmed_messages(
    messages: List[BaseMessage],
    model_name: str = None,
    max_tokens: int = None,
    include_system: bool = True,
    strategy: str = "last"
) -> List[BaseMessage]:
    """
    Trim messages to fit within context window using LangChain's trim_messages utility.
    
    Args:
        messages: List of conversation messages
        model_name: Model name (defaults to OPENAI_MODEL)
        max_tokens: Maximum tokens to keep (defaults to 80% of model context window)
        include_system: Whether to include system messages
        strategy: Trimming strategy ("last" keeps most recent, "first" keeps oldest)
        
    Returns:
        Trimmed list of messages that fit within the context window
    """
    model_name = model_name or OPENAI_MODEL
    
    try:
        # Get model's context window size
        context_window = get_model_context_window(model_name)
        
        # Default to 80% of context window if max_tokens not specified
        if max_tokens is None:
            max_tokens = int(context_window * 0.8)
        
        # Create token counter using the model's tokenizer
        llm = ChatOpenAI(model=model_name)
        
        # Use LangChain's trim_messages utility
        trimmed = trim_messages(
            messages,
            max_tokens=max_tokens,
            token_counter=llm,  # Uses model's tokenizer
            strategy=strategy,  # "last" keeps most recent messages
            include_system=include_system,
            allow_partial=False,
            start_on="human"  # Ensure we start with a human message
        )
        
        logger.info(
            f"Trimmed messages: {len(messages)} -> {len(trimmed)} messages "
            f"(max_tokens={max_tokens}, strategy={strategy})"
        )
        
        return trimmed
        
    except Exception as e:
        logger.error(f"Error trimming messages: {e}", exc_info=True)
        # Return original messages on error
        return messages
