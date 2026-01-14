"""
Prometheus metrics for agent system observability.
"""
from prometheus_client import Counter, Histogram, Gauge
from app.core.logging import get_logger

logger = get_logger(__name__)

# Request metrics
agent_requests_total = Counter(
    'agent_requests_total',
    'Total number of agent requests',
    ['agent_name', 'status']
)

agent_request_duration_seconds = Histogram(
    'agent_request_duration_seconds',
    'Agent request duration in seconds',
    ['agent_name'],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0]
)

tool_calls_total = Counter(
    'tool_calls_total',
    'Total number of tool calls',
    ['tool_name', 'status']
)

tool_call_duration_seconds = Histogram(
    'tool_call_duration_seconds',
    'Tool call duration in seconds',
    ['tool_name'],
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 5.0]
)

# Context usage metrics
context_usage_percentage = Histogram(
    'context_usage_percentage',
    'Context window usage percentage',
    ['model_name'],
    buckets=[10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 100]
)

# Workflow metrics
workflow_activities_total = Counter(
    'workflow_activities_total',
    'Total number of workflow activities',
    ['status']
)

workflow_activity_duration_seconds = Histogram(
    'workflow_activity_duration_seconds',
    'Workflow activity duration in seconds',
    buckets=[1.0, 5.0, 10.0, 30.0, 60.0, 300.0]
)

# Active connections
active_streams = Gauge(
    'active_streams',
    'Number of active SSE streams',
    ['user_id']
)

# Error metrics
agent_errors_total = Counter(
    'agent_errors_total',
    'Total number of agent errors',
    ['agent_name', 'error_type']
)


def record_agent_request(agent_name: str, duration: float, status: str = "success"):
    """Record agent request metrics."""
    agent_requests_total.labels(agent_name=agent_name, status=status).inc()
    agent_request_duration_seconds.labels(agent_name=agent_name).observe(duration)


def record_tool_call(tool_name: str, duration: float, status: str = "success"):
    """Record tool call metrics."""
    tool_calls_total.labels(tool_name=tool_name, status=status).inc()
    tool_call_duration_seconds.labels(tool_name=tool_name).observe(duration)


def record_context_usage(model_name: str, usage_percentage: float):
    """Record context usage metrics."""
    context_usage_percentage.labels(model_name=model_name).observe(usage_percentage)


def record_workflow_activity(duration: float, status: str = "success"):
    """Record workflow activity metrics."""
    workflow_activities_total.labels(status=status).inc()
    workflow_activity_duration_seconds.observe(duration)


def record_error(agent_name: str, error_type: str):
    """Record error metrics."""
    agent_errors_total.labels(agent_name=agent_name, error_type=error_type).inc()


def set_active_streams(user_id: int, count: int):
    """Set active streams count for user."""
    active_streams.labels(user_id=str(user_id)).set(count)
