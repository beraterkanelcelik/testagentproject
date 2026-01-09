"""
Langfuse Metrics API service for querying session statistics.

This module provides functions to query Langfuse Metrics API and Observations API
for token usage, costs, and agent/tool analytics by session_id.
"""
import json
from typing import Dict, Any, Optional, List, Union
from datetime import datetime, timezone
from langfuse import get_client
from app.observability.tracing import LANGFUSE_ENABLED
from app.core.logging import get_logger

logger = get_logger(__name__)


# ============================================================================
# Helper Functions (Private)
# ============================================================================

def _normalize_api_response(response: Any) -> List[Any]:
    """
    Normalize different API response formats to a list.
    
    Args:
        response: API response (object with .data, dict, list, etc.)
        
    Returns:
        List of items
    """
    if hasattr(response, 'data'):
        return response.data if response.data else []
    elif isinstance(response, list):
        return response
    elif isinstance(response, dict):
        return response.get('data', [])
    return []


def _extract_trace_ids(traces: Any) -> List[str]:
    """
    Extract trace IDs from various trace response formats.
    
    Args:
        traces: Trace response from Langfuse API
        
    Returns:
        List of trace ID strings
    """
    trace_list = _normalize_api_response(traces)
    trace_ids = []
    
    for trace in trace_list:
        trace_id = None
        if isinstance(trace, dict):
            trace_id = trace.get('id') or trace.get('traceId')
        else:
            trace_id = getattr(trace, 'id', None) or getattr(trace, 'trace_id', None)
        
        if trace_id:
            trace_ids.append(str(trace_id))
    
    return trace_ids


def _convert_usage_object_to_dict(usage_obj: Any) -> Dict[str, Any]:
    """
    Convert usage object to dictionary format.
    
    Args:
        usage_obj: Usage object from Langfuse SDK
        
    Returns:
        Dictionary with usage data
    """
    if isinstance(usage_obj, dict):
        return usage_obj
    
    if hasattr(usage_obj, 'input') or hasattr(usage_obj, 'output') or hasattr(usage_obj, 'total'):
        return {
            'input': getattr(usage_obj, 'input', None),
            'output': getattr(usage_obj, 'output', None),
            'total': getattr(usage_obj, 'total', None),
        }
    
    return {}


def _convert_observation_to_dict(obs: Any, trace_id: str) -> Optional[Dict[str, Any]]:
    """
    Convert observation object to dictionary, handling immutable ObservationsView objects.
    
    Args:
        obs: Observation object (dict or immutable object)
        trace_id: Trace ID to attach for grouping
        
    Returns:
        Dictionary representation of observation, or None if conversion fails
    """
    if isinstance(obs, dict):
        obs['_trace_id'] = trace_id
        return obs
    
    # Convert immutable object to dict
    try:
        if hasattr(obs, 'dict'):
            obs_dict = obs.dict()
        elif hasattr(obs, '__dict__'):
            obs_dict = dict(obs.__dict__)
        else:
            # Manual attribute extraction
            obs_dict = {}
            attrs = [
                'id', 'type', 'name', 'start_time', 'startTime', 'createdAt',
                'end_time', 'endTime', 'latency', 'metadata', 'usage', 'usage_details',
                'input', 'output', 'trace_id', 'traceId', 'calculated_total_cost',
                'calculated_input_cost', 'calculated_output_cost', 'total_cost'
            ]
            for attr in attrs:
                if hasattr(obs, attr):
                    try:
                        value = getattr(obs, attr, None)
                        if value is not None:
                            obs_dict[attr] = value
                    except Exception:
                        pass
        
        # Handle usage object conversion
        if 'usage' in obs_dict and not isinstance(obs_dict['usage'], dict):
            obs_dict['usage'] = _convert_usage_object_to_dict(obs_dict['usage'])
        
        obs_dict['_trace_id'] = trace_id
        return obs_dict
    except Exception as e:
        logger.warning(f"Failed to convert observation to dict: {e}")
        return None


def _extract_usage_data(obs: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Extract usage data from observation dictionary.
    
    Args:
        obs: Observation dictionary
        
    Returns:
        Usage dictionary or None
    """
    usage = obs.get('usage') or obs.get('usage_details') or obs.get('usageDetails')
    if not usage:
        usage = obs.get('usage_data') or obs.get('tokenUsage') or obs.get('token_usage')
    
    if usage:
        return _convert_usage_object_to_dict(usage)
    return None


def _extract_cost_data(obs: Dict[str, Any], usage: Optional[Dict[str, Any]] = None) -> Dict[str, Optional[float]]:
    """
    Extract cost data from observation and usage.
    
    Args:
        obs: Observation dictionary
        usage: Optional usage dictionary
        
    Returns:
        Dictionary with input_cost, output_cost, total_cost
    """
    costs = {
        'input_cost': None,
        'output_cost': None,
        'total_cost': None,
    }
    
    # Check observation for costs
    costs['input_cost'] = (
        obs.get('calculated_input_cost') or
        obs.get('input_cost') or
        obs.get('inputCost')
    )
    costs['output_cost'] = (
        obs.get('calculated_output_cost') or
        obs.get('output_cost') or
        obs.get('outputCost')
    )
    costs['total_cost'] = (
        obs.get('calculated_total_cost') or
        obs.get('total_cost') or
        obs.get('totalCost')
    )
    
    # Fallback to usage object
    if usage:
        if not costs['input_cost']:
            costs['input_cost'] = usage.get('input_cost') or usage.get('inputCost')
        if not costs['output_cost']:
            costs['output_cost'] = usage.get('output_cost') or usage.get('outputCost')
        if not costs['total_cost']:
            costs['total_cost'] = usage.get('total_cost') or usage.get('totalCost')
    
    return costs


def _extract_observation_fields(obs: Union[Dict[str, Any], Any]) -> Dict[str, Any]:
    """
    Extract common fields from observation (dict or object).
    
    Args:
        obs: Observation (dict or object)
        
    Returns:
        Dictionary with extracted fields
    """
    if isinstance(obs, dict):
        return {
            'id': obs.get('id'),
            'type': obs.get('type'),
            'name': obs.get('name'),
            'start_time': obs.get('start_time') or obs.get('startTime') or obs.get('createdAt'),
            'end_time': obs.get('end_time') or obs.get('endTime'),
            'latency': obs.get('latency'),
            'metadata': obs.get('metadata', {}),
            'usage': obs.get('usage') or obs.get('usage_details'),
            'input': obs.get('input'),
            'output': obs.get('output'),
            'trace_id': obs.get('_trace_id') or obs.get('trace_id') or obs.get('traceId'),
        }
    else:
        return {
            'id': getattr(obs, 'id', None),
            'type': getattr(obs, 'type', None),
            'name': getattr(obs, 'name', None),
            'start_time': (
                getattr(obs, 'start_time', None) or
                getattr(obs, 'startTime', None) or
                getattr(obs, 'createdAt', None)
            ),
            'end_time': (
                getattr(obs, 'end_time', None) or
                getattr(obs, 'endTime', None)
            ),
            'latency': getattr(obs, 'latency', None),
            'metadata': getattr(obs, 'metadata', None) or {},
            'usage': getattr(obs, 'usage', None),
            'input': getattr(obs, 'input', None),
            'output': getattr(obs, 'output', None),
            'trace_id': (
                getattr(obs, '_trace_id', None) or
                getattr(obs, 'trace_id', None) or
                getattr(obs, 'traceId', None)
            ),
        }


def _aggregate_metrics_from_observations(observations: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Aggregate token usage and costs from observations.
    
    Args:
        observations: List of observation dictionaries
        
    Returns:
        Dictionary with aggregated metrics
    """
    total_tokens = 0
    prompt_tokens = 0
    completion_tokens = 0
    total_cost = 0.0
    prompt_cost = 0.0
    completion_cost = 0.0
    observations_with_usage = 0
    
    for obs in observations:
        usage = _extract_usage_data(obs)
        if not usage:
            continue
        
        observations_with_usage += 1
        
        # Extract token counts
        obs_input = usage.get('input') or usage.get('inputTokens') or usage.get('input_tokens') or 0
        obs_output = usage.get('output') or usage.get('outputTokens') or usage.get('output_tokens') or 0
        obs_total = usage.get('total') or usage.get('totalTokens') or usage.get('total_tokens') or 0
        
        # Convert to int
        obs_input = int(obs_input) if obs_input else 0
        obs_output = int(obs_output) if obs_output else 0
        obs_total = int(obs_total) if obs_total else 0
        
        # Extract costs
        costs = _extract_cost_data(obs, usage)
        
        # Aggregate
        total_tokens += obs_total
        prompt_tokens += obs_input
        completion_tokens += obs_output
        
        if costs['total_cost']:
            total_cost += float(costs['total_cost'])
        if costs['input_cost']:
            prompt_cost += float(costs['input_cost'])
        if costs['output_cost']:
            completion_cost += float(costs['output_cost'])
    
    if observations_with_usage == 0 and len(observations) > 0:
        logger.warning(f"No usage data found in {len(observations)} observations")
    
    return {
        "total_tokens": total_tokens,
        "input_tokens": prompt_tokens,
        "output_tokens": completion_tokens,
        "cached_tokens": 0,  # Not directly available from observations
        "cost": {
            "total": total_cost,
            "input": prompt_cost,
            "output": completion_cost,
            "cached": 0.0,
        }
    }


# ============================================================================
# Public API Functions
# ============================================================================

def build_metrics_query(session_id: int, from_timestamp: datetime) -> Dict[str, Any]:
    """
    Build Metrics API query for session statistics.
    
    Works with both v1 (self-hosted) and v2 (Cloud) APIs.
    
    Args:
        session_id: Chat session ID
        from_timestamp: Session creation timestamp
        
    Returns:
        Query dictionary for Metrics API
    """
    # Convert datetime to ISO format with UTC timezone (required format: ends with 'Z')
    if from_timestamp.tzinfo is None:
        from_timestamp = from_timestamp.replace(tzinfo=timezone.utc)
    from_utc = from_timestamp.astimezone(timezone.utc)
    from_iso = from_utc.strftime('%Y-%m-%dT%H:%M:%S') + f".{from_utc.microsecond // 1000:03d}Z"
    
    to_timestamp = datetime.now(timezone.utc)
    to_iso = to_timestamp.strftime('%Y-%m-%dT%H:%M:%S') + f".{to_timestamp.microsecond // 1000:03d}Z"
    
    return {
        "view": "observations",
        "metrics": [
            {"measure": "totalTokens", "aggregation": "sum"},
            {"measure": "inputTokens", "aggregation": "sum"},
            {"measure": "outputTokens", "aggregation": "sum"},
            {"measure": "totalCost", "aggregation": "sum"},
            {"measure": "inputCost", "aggregation": "sum"},
            {"measure": "outputCost", "aggregation": "sum"},
        ],
        "dimensions": [],
        "filters": [
            {
                "column": "sessionId",
                "operator": "=",
                "value": str(session_id),
                "type": "string"
            }
        ],
        "fromTimestamp": from_iso,
        "toTimestamp": to_iso,
    }


def query_session_observations(
    langfuse_client: Any,
    session_id: int,
    from_timestamp: datetime
) -> List[Dict[str, Any]]:
    """
    Query observations for a session to get agent/tool usage.
    
    Uses v1 observations API (compatible with self-hosted Langfuse).
    Falls back to v2 API if available (Langfuse Cloud).
    
    Args:
        langfuse_client: Langfuse client instance
        session_id: Chat session ID
        from_timestamp: Session creation timestamp
        
    Returns:
        List of observation dictionaries
    """
    session_id_str = str(session_id)
    to_timestamp = datetime.now()
    
    # Try v1 API first (works with self-hosted)
    try:
        traces = langfuse_client.api.trace.list(session_id=session_id_str, limit=100)
        trace_ids = _extract_trace_ids(traces)
        
        if not trace_ids:
            logger.debug(f"No traces found for session {session_id}")
            return []
        
        # Get observations for each trace
        all_observations = []
        for trace_id in trace_ids:
            try:
                observations = langfuse_client.api.observations.get_many(
                    trace_id=trace_id,
                    limit=100
                )
                
                obs_list = _normalize_api_response(observations)
                if not obs_list:
                    continue
                
                # Convert observations to dicts and add trace_id
                processed_obs = []
                for obs in obs_list:
                    converted = _convert_observation_to_dict(obs, trace_id)
                    if converted:
                        processed_obs.append(converted)
                
                all_observations.extend(processed_obs)
            except Exception as e:
                logger.warning(f"Failed to get observations for trace {trace_id}: {e}")
                continue
        
        logger.info(f"Retrieved {len(all_observations)} observations from {len(trace_ids)} traces (v1 API)")
        return all_observations
        
    except Exception as v1_error:
        logger.debug(f"v1 observations API failed: {v1_error}, trying v2 API")
        # Fallback to v2 API if available (Langfuse Cloud)
        try:
            observations = langfuse_client.api.observations_v_2.get_many(
                limit=1000,
                fields="core,basic,usage",
                from_start_time=from_timestamp,
                to_start_time=to_timestamp,
                filter=json.dumps([
                    {
                        "type": "string",
                        "column": "sessionId",
                        "operator": "=",
                        "value": session_id_str
                    }
                ])
            )
            
            all_observations = _normalize_api_response(observations)
            logger.debug(f"Retrieved {len(all_observations)} observations (v2 API)")
            return all_observations
        except Exception as v2_error:
            logger.warning(f"Both v1 and v2 observations APIs failed. v1: {v1_error}, v2: {v2_error}")
            return []


def extract_metrics_from_response(metrics_result: Any) -> Dict[str, Any]:
    """
    Extract metrics from Langfuse Metrics API v2 response.
    
    Args:
        metrics_result: Response from metrics.metrics()
        
    Returns:
        Dictionary with extracted metrics
    """
    try:
        data_array = _normalize_api_response(metrics_result)
        
        if not data_array or not isinstance(data_array[0], dict):
            return _get_empty_metrics()
        
        metrics_obj = data_array[0]
        
        return {
            "total_tokens": int(metrics_obj.get('totalTokens_sum', 0) or 0),
            "input_tokens": int(metrics_obj.get('inputTokens_sum', 0) or 0),
            "output_tokens": int(metrics_obj.get('outputTokens_sum', 0) or 0),
            "cached_tokens": 0,  # Not directly available in metrics
            "cost": {
                "total": float(metrics_obj.get('totalCost_sum', 0) or 0.0),
                "input": float(metrics_obj.get('inputCost_sum', 0) or 0.0),
                "output": float(metrics_obj.get('outputCost_sum', 0) or 0.0),
                "cached": 0.0,
            }
        }
    except Exception as e:
        logger.error(f"Failed to extract metrics from response: {e}", exc_info=True)
        return _get_empty_metrics()


def _get_empty_metrics() -> Dict[str, Any]:
    """Return empty metrics structure."""
    return {
        "total_tokens": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cached_tokens": 0,
        "cost": {
            "total": 0.0,
            "input": 0.0,
            "output": 0.0,
            "cached": 0.0,
        }
    }


def aggregate_agent_tool_usage(observations: List[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    """
    Aggregate agent and tool usage from observations.
    
    Args:
        observations: List of observation dictionaries
        
    Returns:
        Dictionary with 'agent_usage' and 'tool_usage' keys
    """
    agent_usage: Dict[str, int] = {}
    tool_usage: Dict[str, int] = {}
    
    for obs in observations:
        obs_type = obs.get('type')
        obs_name = obs.get('name')
        metadata = obs.get('metadata', {})
        trace_name = obs.get('traceName') or obs.get('trace_name')
        
        # Identify agents from GENERATION observations
        if obs_type == "GENERATION":
            agent_name = None
            
            # Check observation name
            if obs_name:
                name_lower = str(obs_name).lower()
                if 'greeter' in name_lower:
                    agent_name = 'greeter'
                elif 'supervisor' in name_lower:
                    agent_name = 'supervisor'
                elif 'gmail' in name_lower:
                    agent_name = 'gmail'
            
            # Check trace name
            if not agent_name and trace_name:
                trace_lower = str(trace_name).lower()
                if 'greeter' in trace_lower:
                    agent_name = 'greeter'
                elif 'supervisor' in trace_lower:
                    agent_name = 'supervisor'
                elif 'gmail' in trace_lower:
                    agent_name = 'gmail'
            
            # Check metadata
            if not agent_name and metadata and isinstance(metadata, dict):
                agent_name = metadata.get('agent_name') or metadata.get('agentName')
                if agent_name:
                    agent_name = str(agent_name).lower()
            
            if agent_name:
                agent_usage[agent_name] = agent_usage.get(agent_name, 0) + 1
        
        # Identify tools from SPAN observations
        if obs_type == "SPAN" and metadata and isinstance(metadata, dict):
            tool_calls = metadata.get('tool_calls') or metadata.get('toolCalls')
            if tool_calls and isinstance(tool_calls, list):
                for tool_call in tool_calls:
                    if isinstance(tool_call, dict):
                        tool_name = tool_call.get('tool') or tool_call.get('name', 'unknown')
                        tool_usage[str(tool_name)] = tool_usage.get(str(tool_name), 0) + 1
            
            # Check if observation name suggests a tool
            if obs_name:
                name_lower = str(obs_name).lower()
                if 'tool' in name_lower or 'invoke' in name_lower:
                    tool_name = obs_name.split('.')[-1] if '.' in obs_name else obs_name
                    tool_usage[str(tool_name)] = tool_usage.get(str(tool_name), 0) + 1
    
    return {
        "agent_usage": agent_usage,
        "tool_usage": tool_usage,
    }


def get_session_metrics_from_langfuse(session_id: int) -> Optional[Dict[str, Any]]:
    """
    Query Langfuse Metrics API for session statistics.
    
    Uses observations view to get:
    - Token usage (input, output, total)
    - Costs (input, output, total)
    - Agent/tool usage from observations
    - Activity timeline
    
    Args:
        session_id: Chat session ID
        
    Returns:
        Dictionary with metrics or None if unavailable
    """
    if not LANGFUSE_ENABLED:
        logger.warning("Langfuse is disabled, cannot get metrics")
        return None
    
    try:
        langfuse = get_client()
        if not langfuse:
            logger.warning("Langfuse client unavailable")
            return None
        
        # Get session from database for time range
        from app.db.models.session import ChatSession
        try:
            session = ChatSession.objects.get(id=session_id)
        except ChatSession.DoesNotExist:
            logger.error(f"Session {session_id} not found")
            return None
        
        # Query observations (needed for agent/tool usage and fallback metrics)
        observations = query_session_observations(langfuse, session_id, session.created_at)
        
        # Try Metrics API first (works on Langfuse Cloud, may not work on self-hosted)
        metrics_data = None
        try:
            metrics_query = build_metrics_query(session_id, session.created_at)
            metrics_result = langfuse.api.metrics.metrics(query=json.dumps(metrics_query))
            metrics_data = extract_metrics_from_response(metrics_result)
            logger.info(f"Metrics API succeeded: {metrics_data}")
        except Exception as e:
            logger.debug(f"Metrics API query failed (expected on self-hosted): {e}")
            metrics_data = None
        
        # If Metrics API failed or unavailable, aggregate from observations
        if metrics_data is None or (metrics_data.get('total_tokens', 0) == 0 and len(observations) > 0):
            logger.info(f"Aggregating metrics from {len(observations)} observations")
            metrics_data = _aggregate_metrics_from_observations(observations)
            logger.info(
                f"Aggregated metrics: total_tokens={metrics_data['total_tokens']}, "
                f"input_tokens={metrics_data['input_tokens']}, "
                f"output_tokens={metrics_data['output_tokens']}, "
                f"total_cost={metrics_data['cost']['total']}"
            )
        
        # Aggregate agent/tool usage from observations
        usage_stats = aggregate_agent_tool_usage(observations)
        
        # Format observations into user-friendly timeline
        timeline = format_observations_timeline(observations)
        
        # Combine metrics and usage stats
        return {
            **metrics_data,
            "agent_usage": usage_stats["agent_usage"],
            "tool_usage": usage_stats["tool_usage"],
            "activity_timeline": timeline,
        }
    
    except Exception as e:
        logger.error(f"Failed to get Langfuse metrics for session {session_id}: {e}", exc_info=True)
        return None


# ============================================================================
# Timeline Formatting
# ============================================================================

def format_observations_timeline(observations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Format observations into a user-friendly activity timeline.
    
    Similar to Langfuse's trace view, showing agent interactions, tool calls,
    and LLM generations in chronological order.
    
    Args:
        observations: List of observation dictionaries from Langfuse
        
    Returns:
        List of formatted activity items
    """
    timeline = []
    
    for obs in observations:
        fields = _extract_observation_fields(obs)
        
        # Build activity base
        activity: Dict[str, Any] = {
            'id': str(fields['id']) if fields['id'] else None,
            'trace_id': str(fields['trace_id']) if fields['trace_id'] else None,
            'type': fields['type'] or 'UNKNOWN',
            'timestamp': (
                fields['start_time'].isoformat()
                if hasattr(fields['start_time'], 'isoformat')
                else str(fields['start_time']) if fields['start_time'] else None
            ),
            'latency_ms': float(fields['latency']) * 1000 if fields['latency'] else None,
        }
        
        # Extract usage and tokens
        usage = fields.get('usage')
        if usage:
            usage_dict = _convert_usage_object_to_dict(usage)
            if usage_dict:
                activity['tokens'] = {
                    'input': int(usage_dict.get('input') or usage_dict.get('inputTokens') or usage_dict.get('input_tokens') or 0),
                    'output': int(usage_dict.get('output') or usage_dict.get('outputTokens') or usage_dict.get('output_tokens') or 0),
                    'total': int(usage_dict.get('total') or usage_dict.get('totalTokens') or usage_dict.get('total_tokens') or 0),
                }
                costs = _extract_cost_data(obs, usage_dict)
                activity['cost'] = costs['total_cost']
        
        # Format based on observation type
        obs_type = fields['type']
        obs_name = fields['name']
        metadata = fields.get('metadata', {})
        input_data = fields.get('input')
        output_data = fields.get('output')
        
        if obs_type == "GENERATION":
            activity['category'] = 'llm_call'
            activity['name'] = obs_name or 'LLM Call'
            
            # Identify agent
            agent_name = None
            if obs_name:
                name_lower = str(obs_name).lower()
                if 'greeter' in name_lower:
                    agent_name = 'greeter'
                elif 'supervisor' in name_lower:
                    agent_name = 'supervisor'
                elif 'gmail' in name_lower:
                    agent_name = 'gmail'
            
            if agent_name:
                activity['agent'] = agent_name
                activity['name'] = f"{agent_name.title()} Agent"
            
            # Extract model
            if isinstance(metadata, dict):
                activity['model'] = metadata.get('model') or metadata.get('model_name')
            
            # Truncate input/output
            if input_data:
                activity['input_preview'] = str(input_data)[:200]
            if output_data:
                activity['output_preview'] = str(output_data)[:200]
                
        elif obs_type == "SPAN":
            activity['category'] = 'tool_call'
            activity['name'] = obs_name or 'Tool Call'
            
            # Check for tool calls
            if isinstance(metadata, dict):
                tool_calls = metadata.get('tool_calls') or metadata.get('toolCalls')
                if tool_calls:
                    activity['tools'] = []
                    for tool_call in (tool_calls if isinstance(tool_calls, list) else [tool_calls]):
                        if isinstance(tool_call, dict):
                            tool_name = tool_call.get('tool') or tool_call.get('name', 'unknown')
                            activity['tools'].append({
                                'name': tool_name,
                                'input': tool_call.get('input') or tool_call.get('arguments'),
                            })
                elif obs_name:
                    name_lower = str(obs_name).lower()
                    if 'tool' in name_lower or 'invoke' in name_lower:
                        activity['tool'] = obs_name.split('.')[-1] if '.' in obs_name else obs_name
            
            # Add input/output preview
            if input_data:
                activity['input_preview'] = str(input_data)[:200]
            if output_data:
                activity['output_preview'] = str(output_data)[:200]
                
        elif obs_type == "EVENT":
            activity['category'] = 'event'
            activity['name'] = obs_name or 'Event'
            if input_data:
                activity['message'] = str(input_data)[:200]
        else:
            activity['category'] = 'other'
            activity['name'] = obs_name or f"{obs_type or 'Unknown'} Operation"
        
        timeline.append(activity)
    
    # Sort by timestamp (oldest first)
    timeline.sort(key=lambda x: x.get('timestamp') or '', reverse=False)
    return timeline
