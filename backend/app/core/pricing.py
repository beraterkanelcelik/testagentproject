"""
Pricing configuration for different models.
This allows easy model switching and price calculation.
"""
from typing import Dict, Optional
from decimal import Decimal

# Pricing per 1M tokens (in USD)
MODEL_PRICING: Dict[str, Dict[str, Decimal]] = {
    "gpt-4o-mini-2024-07-18": {
        "input": Decimal("0.15"),
        "cached_input": Decimal("0.075"),  # 50% of input price (typical)
        "output": Decimal("0.60"),
    },
    "gpt-4.1-mini-2025-04-14": {
        "input": Decimal("0.40"),
        "cached_input": Decimal("0.10"),
        "output": Decimal("1.60"),
    },
    "gpt-4o-mini": {
        "input": Decimal("0.15"),
        "cached_input": Decimal("0.075"),
        "output": Decimal("0.60"),
    },
    # Add more models as needed
}

# Default model pricing (fallback)
DEFAULT_PRICING = {
    "input": Decimal("0.15"),
    "cached_input": Decimal("0.075"),
    "output": Decimal("0.60"),
}


def get_model_pricing(model_name: str) -> Dict[str, Decimal]:
    """
    Get pricing for a specific model.
    
    Args:
        model_name: Model identifier
        
    Returns:
        Dictionary with input, cached_input, and output prices per 1M tokens
    """
    # Try exact match first
    if model_name in MODEL_PRICING:
        return MODEL_PRICING[model_name]
    
    # Try partial match (e.g., "gpt-4o-mini" matches "gpt-4o-mini-2024-07-18")
    for key, pricing in MODEL_PRICING.items():
        if model_name.startswith(key) or key.startswith(model_name):
            return pricing
    
    # Return default pricing if model not found
    return DEFAULT_PRICING


def calculate_cost(
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int = 0,
    model_name: Optional[str] = None
) -> Dict[str, Decimal]:
    """
    Calculate cost for token usage.
    
    Args:
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens
        cached_tokens: Number of cached input tokens
        model_name: Model identifier (optional, uses default if not provided)
        
    Returns:
        Dictionary with total_cost, input_cost, output_cost, cached_cost
    """
    pricing = get_model_pricing(model_name) if model_name else DEFAULT_PRICING
    
    # Calculate costs (prices are per 1M tokens)
    input_cost = (Decimal(input_tokens) / Decimal(1_000_000)) * pricing["input"]
    cached_cost = (Decimal(cached_tokens) / Decimal(1_000_000)) * pricing["cached_input"]
    output_cost = (Decimal(output_tokens) / Decimal(1_000_000)) * pricing["output"]
    
    total_cost = input_cost + cached_cost + output_cost
    
    return {
        "total_cost": total_cost,
        "input_cost": input_cost,
        "cached_cost": cached_cost,
        "output_cost": output_cost,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_tokens": cached_tokens,
    }
