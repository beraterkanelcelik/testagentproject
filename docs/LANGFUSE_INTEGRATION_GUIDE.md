# Langfuse Integration Guide

> **Living Document**: This guide is continuously updated as we learn new patterns and best practices. When implementing Langfuse in a new project or discovering improvements, update this document accordingly.

**Version**: 1.0  
**Last Updated**: 2026-01-10  
**Compatible With**: Langfuse SDK v3+, LangChain latest, LangGraph latest, Django 5.0+, OpenAI API

---

## Table of Contents

1. [Overview & Architecture](#1-overview--architecture)
2. [Prerequisites & Setup](#2-prerequisites--setup)
3. [Core Configuration](#3-core-configuration)
4. [LangChain Integration](#4-langchain-integration)
5. [LangGraph Integration](#5-langgraph-integration)
6. [Streaming vs Non-Streaming Patterns](#6-streaming-vs-non-streaming-patterns)
7. [OpenAI Integration](#7-openai-integration)
8. [Django-Specific Patterns](#8-django-specific-patterns)
9. [Docker Setup](#9-docker-setup)
10. [Best Practices](#10-best-practices)
11. [Common Patterns & Code Templates](#11-common-patterns--code-templates)
12. [Troubleshooting](#12-troubleshooting)
13. [Advanced Topics](#13-advanced-topics)
14. [Metrics API & Analytics](#14-metrics-api--analytics)
15. [Maintenance & Updates](#15-maintenance--updates)

---

## 1. Overview & Architecture

### What is Langfuse?

Langfuse is an open-source observability platform for LLM applications. It provides:

- **Tracing**: Track complete execution flows of LLM applications
- **Monitoring**: Monitor token usage, latency, and costs
- **Debugging**: Inspect inputs, outputs, and intermediate steps
- **Analytics**: Analyze performance and usage patterns

### Architecture Flow

```mermaid
graph TB
    Django[Django Web App] -->|HTTP Request| LangGraph[LangGraph Agent]
    LangGraph -->|Orchestrates| LangChain[LangChain Chains]
    LangChain -->|Calls| OpenAI[OpenAI API]
    LangChain -->|Traces via| CallbackHandler[Langfuse CallbackHandler]
    CallbackHandler -->|Sends Traces| Langfuse[Langfuse Server]
    Django -->|User Context| CallbackHandler
    LangGraph -->|State Updates| CallbackHandler
```

### Key Concepts

#### Trace Hierarchy

```mermaid
graph TD
    Trace[Trace - Root Level] -->|contains| Span1[Span - LangGraph Execution]
    Trace -->|contains| Span2[Span - Agent Node]
    Span1 -->|contains| Chain1[Chain - Supervisor]
    Span2 -->|contains| Chain2[Chain - Greeter Agent]
    Chain1 -->|contains| Generation1[Generation - LLM Call]
    Chain2 -->|contains| Generation2[Generation - LLM Call]
```

- **Trace**: Top-level execution unit (one per user request)
- **Span**: Represents a function or operation (e.g., graph execution, node execution)
- **Chain**: Represents a sequence of operations (e.g., agent execution)
- **Generation**: Represents an LLM call (input, output, tokens, latency)

### SDK v3 vs v2 Differences

**SDK v3 (Current)**:
- Uses OpenTelemetry under the hood
- Automatic environment variable reading
- `get_client()` singleton pattern
- `propagate_attributes()` for context propagation
- `CallbackHandler()` with no constructor arguments

**SDK v2 (Deprecated)**:
- Manual client initialization
- Explicit public/secret key passing
- Different callback handler API

**This guide focuses on SDK v3 patterns.**

---

## 2. Prerequisites & Setup

### Required Packages

```python
# requirements.txt
langfuse>=3.0.0          # Langfuse SDK v3
langchain>=0.1.0          # LangChain core
langchain-core>=0.1.0     # LangChain core components
langchain-openai>=0.1.0   # OpenAI integration
langgraph>=0.0.40         # LangGraph for agent orchestration
langgraph-checkpoint-postgres>=2.0.0  # PostgreSQL checkpointing
```

### Environment Variables

```bash
# Langfuse Configuration
LANGFUSE_PUBLIC_KEY=your_public_key_here
LANGFUSE_SECRET_KEY=your_secret_key_here
LANGFUSE_BASE_URL=http://langfuse:3000  # For self-hosted
# OR
LANGFUSE_BASE_URL=https://cloud.langfuse.com  # For cloud

# Enable/disable flag
LANGFUSE_ENABLED=true

# OpenAI Configuration
OPENAI_API_KEY=your_openai_key_here
OPENAI_MODEL=gpt-4o-mini  # Default model

# Optional: LangSmith (for compatibility)
LANGCHAIN_TRACING_V2=false
LANGCHAIN_PROJECT=your-project-name
```

### Langfuse Server Setup

#### Option 1: Self-Hosted (Docker Compose)

See [Docker Setup](#9-docker-setup) section for complete configuration.

#### Option 2: Cloud (Langfuse Cloud)

1. Sign up at https://cloud.langfuse.com
2. Create a project
3. Get your public/secret keys from the dashboard
4. Set `LANGFUSE_BASE_URL=https://cloud.langfuse.com`

---

## 3. Core Configuration

### Centralized Tracing Module

Create a centralized module for all Langfuse operations:

```python
# observability/tracing.py
"""
Langfuse AI tracing and observability hooks (v3 SDK).
"""
from typing import Optional, Dict, Any
from langfuse import get_client
from langfuse.langchain import CallbackHandler
from app.core.config import (
    LANGFUSE_PUBLIC_KEY,
    LANGFUSE_SECRET_KEY,
    LANGFUSE_BASE_URL,
    LANGFUSE_ENABLED
)
from app.core.logging import get_logger

logger = get_logger(__name__)


def get_langfuse_client():
    """
    Get the Langfuse client instance using singleton pattern.
    
    SDK v3: get_client() reads from environment variables automatically.
    Returns None if Langfuse is disabled or not configured.
    
    Returns:
        Langfuse client instance or None
    """
    if not LANGFUSE_ENABLED:
        return None
    
    if not LANGFUSE_PUBLIC_KEY or not LANGFUSE_SECRET_KEY:
        logger.warning("Langfuse keys not configured")
        return None
    
    try:
        # SDK v3: get_client() reads from environment automatically
        return get_client()
    except Exception as e:
        logger.error(f"Failed to get Langfuse client: {e}", exc_info=True)
        return None


def get_callback_handler() -> Optional[CallbackHandler]:
    """
    Get Langfuse CallbackHandler for LangChain integration.
    
    SDK v3: CallbackHandler reads from environment variables automatically.
    No constructor arguments needed.
    
    Returns:
        CallbackHandler instance or None if disabled
    """
    if not LANGFUSE_ENABLED:
        return None
    
    if not LANGFUSE_PUBLIC_KEY or not LANGFUSE_SECRET_KEY:
        return None
    
    try:
        # SDK v3: CallbackHandler reads from environment automatically
        return CallbackHandler()
    except Exception as e:
        logger.error(f"Failed to create CallbackHandler: {e}", exc_info=True)
        return None


def prepare_trace_context(
    user_id: int,
    session_id: Optional[int] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Prepare trace context for propagate_attributes().
    
    This returns a dictionary that can be used with propagate_attributes()
    to set user_id, session_id, and metadata on traces.
    
    Args:
        user_id: User ID
        session_id: Optional session ID
        metadata: Optional additional metadata
        
    Returns:
        Dictionary with user_id, session_id, and metadata for propagate_attributes()
    """
    context = {
        "user_id": str(user_id),
    }
    
    if session_id:
        context["session_id"] = str(session_id)
    
    if metadata:
        # Convert all metadata values to strings (required by propagate_attributes)
        context["metadata"] = {
            k: str(v) if not isinstance(v, str) else v
            for k, v in metadata.items()
        }
    
    return context


def flush_traces():
    """
    Flush all pending traces to Langfuse.
    
    This ensures traces are sent immediately rather than waiting for background processes.
    Should be called in short-lived applications or before shutdown.
    """
    if not LANGFUSE_ENABLED:
        return
    
    try:
        client = get_langfuse_client()
        if client and hasattr(client, 'flush'):
            client.flush()
            logger.debug("Flushed Langfuse traces")
    except Exception as e:
        logger.error(f"Failed to flush Langfuse traces: {e}", exc_info=True)


def shutdown_client():
    """
    Gracefully shutdown the Langfuse client.
    
    This flushes all pending data and waits for background threads to finish.
    Should be called before application exit.
    """
    if not LANGFUSE_ENABLED:
        return
    
    try:
        client = get_langfuse_client()
        if client and hasattr(client, 'shutdown'):
            client.shutdown()
            logger.debug("Shutdown Langfuse client")
    except Exception as e:
        logger.error(f"Failed to shutdown Langfuse client: {e}", exc_info=True)
```

### Configuration Management

```python
# core/config.py
import os
from dotenv import load_dotenv

load_dotenv()

# Langfuse configuration (v3 SDK)
LANGFUSE_PUBLIC_KEY = os.getenv('LANGFUSE_PUBLIC_KEY', '')
LANGFUSE_SECRET_KEY = os.getenv('LANGFUSE_SECRET_KEY', '')
LANGFUSE_BASE_URL = os.getenv('LANGFUSE_BASE_URL', 'http://langfuse:3000')
LANGFUSE_ENABLED = os.getenv('LANGFUSE_ENABLED', 'true') == 'true'

# OpenAI configuration
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '')
OPENAI_MODEL = os.getenv('OPENAI_MODEL', 'gpt-4o-mini')
```

---

## 4. LangChain Integration

### Basic Setup

LangChain integration is automatic via `CallbackHandler`. The handler intercepts all LangChain operations and creates traces.

```python
from langfuse.langchain import CallbackHandler
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

# Create callback handler
callback_handler = CallbackHandler()  # Reads from environment automatically

# Initialize LLM
llm = ChatOpenAI(
    model="gpt-4o-mini",
    temperature=0.7,
)

# Invoke with callbacks
messages = [HumanMessage(content="Hello!")]
response = llm.invoke(
    messages,
    config={"callbacks": [callback_handler]}
)
```

### Passing Callbacks Through Chains

Callbacks propagate automatically through LangChain chains when passed in config:

```python
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

# Create chain
prompt = ChatPromptTemplate.from_template("Answer: {question}")
chain = prompt | llm | StrOutputParser()

# Execute with callbacks
result = chain.invoke(
    {"question": "What is AI?"},
    config={"callbacks": [callback_handler]}
)
```

### Token Usage Extraction

Token usage is automatically captured by the callback handler:

```python
response = llm.invoke(messages, config={"callbacks": [callback_handler]})

# Token usage is in response metadata
if hasattr(response, 'usage_metadata'):
    usage = response.usage_metadata
    total_tokens = usage.get('total_tokens', 0)
    input_tokens = usage.get('input_tokens', 0)
    output_tokens = usage.get('output_tokens', 0)
elif hasattr(response, 'response_metadata'):
    usage = response.response_metadata.get('token_usage', {})
    total_tokens = usage.get('total_tokens', 0)
```

---

## 5. LangGraph Integration

### Graph Execution Patterns

LangGraph automatically creates trace structure when callbacks are passed through the graph execution.

#### Non-Streaming Execution

```python
from langgraph.graph import StateGraph
from langfuse import propagate_attributes
from observability.tracing import get_callback_handler, prepare_trace_context

# Create graph
graph = StateGraph(YourState)
# ... add nodes and edges ...
compiled_graph = graph.compile()

# Prepare config with callbacks
config = {}
callback_handler = get_callback_handler()
if callback_handler:
    config['callbacks'] = [callback_handler]

# Prepare trace context
trace_context = prepare_trace_context(
    user_id=user_id,
    session_id=session_id,
    metadata={"execution_type": "graph"}
)

# Execute with context propagation
with propagate_attributes(**trace_context):
    final_state = compiled_graph.invoke(initial_state, config=config)

# Flush traces
flush_traces()
```

#### Streaming Execution

```python
# Prepare config with callbacks (same as non-streaming)
config = {}
callback_handler = get_callback_handler()
if callback_handler:
    config['callbacks'] = [callback_handler]

# Prepare trace context
trace_context = prepare_trace_context(
    user_id=user_id,
    session_id=session_id,
    metadata={"execution_type": "streaming"}
)

# Stream with both messages and updates modes
with propagate_attributes(**trace_context):
    for event in compiled_graph.stream(
        initial_state,
        config=config,
        stream_mode=["messages", "updates"]
    ):
        # event is a tuple: (mode, data) when using multiple stream modes
        if isinstance(event, tuple) and len(event) == 2:
            mode, data = event
            
            if mode == "messages":
                # data is a tuple: (message_chunk, metadata)
                if isinstance(data, tuple) and len(data) == 2:
                    message_chunk, metadata = data
                    # Process streaming tokens
                    if message_chunk and hasattr(message_chunk, 'content'):
                        yield message_chunk.content
            
            elif mode == "updates":
                # data is a dict with state updates
                if isinstance(data, dict):
                    # Track state changes
                    pass

# Flush traces
flush_traces()
```

### Callback Propagation Through Nodes

Graph nodes receive `config` parameter automatically. Pass it to agent calls:

```python
def your_node(state: YourState, config: dict = None) -> YourState:
    """
    Graph node implementation.
    
    Args:
        state: Current graph state
        config: Optional runtime config (contains callbacks from graph.invoke())
    """
    messages = state.get("messages", [])
    
    # Pass config to agent.invoke() so callbacks propagate to LLM calls
    invoke_kwargs = {}
    if config:
        invoke_kwargs['config'] = config
    
    # Agent call with callback propagation
    response = your_agent.invoke(messages, **invoke_kwargs)
    
    # Update state
    state["messages"].append(response)
    return state
```

### State Management with Tracing

Use state metadata to track execution type and avoid duplicate operations:

```python
# In streaming execution, mark state
initial_state = {
    "messages": messages,
    "metadata": {
        "execution_type": "streaming",  # Mark as streaming
        "trace_id": trace_id,
    }
}

# In nodes, check execution type
def your_node(state: YourState, config: dict = None) -> YourState:
    metadata = state.get("metadata", {})
    execution_type = metadata.get("execution_type", "")
    is_streaming = execution_type == "streaming"
    
    # Conditionally save to database
    if not is_streaming:
        # Save to database (non-streaming)
        save_message_to_db(response)
    # Streaming function handles saving after all tokens are accumulated
```

---

## 6. Streaming vs Non-Streaming Patterns

### Key Differences

| Aspect | Non-Streaming | Streaming |
|--------|--------------|-----------|
| **Method** | `graph.invoke()` | `graph.stream()` |
| **Response** | Complete final state | Iterator of events |
| **Trace Structure** | Created automatically | Created automatically |
| **Message Saving** | Save in nodes | Save after streaming completes |
| **Token Usage** | From final response | From streaming chunks or final state |
| **Use Case** | Synchronous operations | Real-time user feedback |

### When to Use Each

**Non-Streaming**:
- Background jobs
- API endpoints that return complete responses
- Batch processing
- When you don't need real-time feedback

**Streaming**:
- Chat interfaces
- Real-time user feedback
- Long-running operations
- When you want to show progress

### Implementation Pattern

```python
# Non-Streaming Pattern
def execute_agent(user_id, session_id, message):
    # ... setup ...
    
    with propagate_attributes(**trace_context):
        final_state = graph.invoke(initial_state, config=config)
    
    # Extract response
    response = final_state["messages"][-1].content
    
    flush_traces()
    return {"response": response}


# Streaming Pattern
def stream_agent_events(user_id, session_id, message):
    # ... setup ...
    # Mark state as streaming
    initial_state["metadata"]["execution_type"] = "streaming"
    
    accumulated_content = ""
    
    with propagate_attributes(**trace_context):
        for event in graph.stream(initial_state, config=config, stream_mode=["messages", "updates"]):
            if isinstance(event, tuple) and len(event) == 2:
                mode, data = event
                if mode == "messages":
                    # Stream tokens
                    message_chunk, metadata = data
                    if message_chunk and hasattr(message_chunk, 'content'):
                        accumulated_content += message_chunk.content
                        yield {"type": "token", "data": message_chunk.content}
    
    # Save complete message after streaming
    save_message_to_db(accumulated_content)
    flush_traces()
```

### Avoiding Duplicate Messages

**Problem**: Nodes save messages, and streaming function also saves → duplicates.

**Solution**: Use `execution_type` in state metadata:

```python
# In streaming function
initial_state["metadata"]["execution_type"] = "streaming"

# In nodes
def node(state, config=None):
    metadata = state.get("metadata", {})
    is_streaming = metadata.get("execution_type") == "streaming"
    
    if not is_streaming:
        save_message_to_db(response)  # Only save in non-streaming
```

---

## 7. OpenAI Integration

### LLM Initialization

```python
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    model="gpt-4o-mini",
    temperature=0.7,
    api_key=OPENAI_API_KEY,
    streaming=True,  # Enable streaming
    stream_usage=True,  # Enable token usage in streaming responses
)
```

### Streaming Token Handling

```python
def stream_llm_response(messages, config=None):
    accumulated_content = ""
    
    for chunk in llm.stream(messages, config=config):
        if hasattr(chunk, 'content'):
            chunk_content = chunk.content or ""
            if chunk_content:
                # Handle incremental content (OpenAI streaming format)
                if chunk_content.startswith(accumulated_content):
                    delta = chunk_content[len(accumulated_content):]
                    if delta:
                        accumulated_content = chunk_content
                        yield delta
                else:
                    accumulated_content += chunk_content
                    yield chunk_content
```

### Token Usage Metadata Extraction

```python
# From non-streaming response
response = llm.invoke(messages, config=config)

# Check usage_metadata first (OpenAI streaming format)
if hasattr(response, 'usage_metadata') and response.usage_metadata:
    usage = response.usage_metadata
    total_tokens = usage.get('total_tokens', 0)
    input_tokens = usage.get('input_tokens', 0)
    output_tokens = usage.get('output_tokens', 0)
    cached_tokens = usage.get('cached_tokens', 0)

# Fallback to response_metadata
elif hasattr(response, 'response_metadata') and response.response_metadata:
    usage = response.response_metadata.get('token_usage', {})
    if usage:
        total_tokens = usage.get('total_tokens', 0)
        input_tokens = usage.get('prompt_tokens', 0) or usage.get('input_tokens', 0)
        output_tokens = usage.get('completion_tokens', 0) or usage.get('output_tokens', 0)
```

### Error Handling

```python
try:
    response = llm.invoke(messages, config=config)
except Exception as e:
    logger.error(f"LLM invocation failed: {e}", exc_info=True)
    # Flush traces even on error
    flush_traces()
    raise
```

---

## 8. Django-Specific Patterns

### View Integration

```python
from django.http import JsonResponse, StreamingHttpResponse
from langfuse import propagate_attributes
from observability.tracing import get_callback_handler, prepare_trace_context, flush_traces

@csrf_exempt
@require_http_methods(["POST"])
def run_agent(request):
    """Non-streaming agent execution."""
    user = get_current_user(request)
    if not user:
        return JsonResponse({'error': 'Authentication required'}, status=401)
    
    data = json.loads(request.body)
    chat_session_id = data.get('chat_session_id')
    message = data.get('message', '').strip()
    
    # Prepare trace context
    trace_context = prepare_trace_context(
        user_id=user.id,
        session_id=chat_session_id,
        metadata={"endpoint": "run_agent"}
    )
    
    try:
        # Execute agent with tracing
        result = execute_agent(
            user_id=user.id,
            chat_session_id=chat_session_id,
            message=message
        )
        return JsonResponse(result)
    except Exception as e:
        logger.error(f"Error in run_agent: {e}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def stream_agent(request):
    """Streaming agent execution."""
    user = get_current_user(request)
    if not user:
        return JsonResponse({'error': 'Authentication required'}, status=401)
    
    data = json.loads(request.body)
    chat_session_id = data.get('chat_session_id')
    message = data.get('message', '').strip()
    
    def event_stream():
        try:
            for event in stream_agent_events(
                user_id=user.id,
                chat_session_id=chat_session_id,
                message=message
            ):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as e:
            logger.error(f"Error in agent stream: {e}", exc_info=True)
            error_event = {"type": "error", "data": {"error": str(e)}}
            yield f"data: {json.dumps(error_event)}\n\n"
    
    response = StreamingHttpResponse(event_stream(), content_type='text/event-stream')
    response['Cache-Control'] = 'no-cache'
    return response
```

### User/Session Context Propagation

Always pass user and session context through `propagate_attributes()`:

```python
trace_context = prepare_trace_context(
    user_id=user.id,
    session_id=chat_session_id,
    metadata={
        "chat_session_id": chat_session_id,
        "execution_type": "graph",
        "trace_id": trace_id,
    }
)

with propagate_attributes(**trace_context):
    # All traces within this context will have user_id and session_id
    result = graph.invoke(state, config=config)
```

### Database Transaction Considerations

Langfuse tracing is asynchronous and doesn't interfere with database transactions. However, ensure traces are flushed after transactions complete:

```python
from django.db import transaction

@transaction.atomic
def save_with_tracing(user_id, session_id, message):
    # Save to database
    message_obj = Message.objects.create(...)
    
    # Execute agent with tracing
    result = execute_agent(user_id, session_id, message)
    
    # Flush traces after transaction
    flush_traces()
    
    return result
```

---

## 9. Docker Setup

### Docker Compose Configuration

```yaml
services:
  # Your Django Backend
  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    environment:
      - LANGFUSE_PUBLIC_KEY=${LANGFUSE_PUBLIC_KEY}
      - LANGFUSE_SECRET_KEY=${LANGFUSE_SECRET_KEY}
      - LANGFUSE_BASE_URL=http://langfuse-web:3000
      - LANGFUSE_ENABLED=true
      - OPENAI_API_KEY=${OPENAI_API_KEY}
    depends_on:
      - langfuse-web
    networks:
      - app-network

  # Langfuse Services
  langfuse-web:
    image: docker.io/langfuse/langfuse-web:3
    ports:
      - "3000:3000"
    environment:
      - DATABASE_URL=postgresql://postgres:postgres@postgres:5432/langfuse
      - NEXTAUTH_URL=http://localhost:3000
      - SALT=${LANGFUSE_SALT}
      - ENCRYPTION_KEY=${LANGFUSE_ENCRYPTION_KEY}
    depends_on:
      - postgres
      - clickhouse
    networks:
      - app-network

  langfuse-worker:
    image: docker.io/langfuse/langfuse-worker:3
    environment:
      - DATABASE_URL=postgresql://postgres:postgres@postgres:5432/langfuse
      - CLICKHOUSE_URL=http://clickhouse:8123
    depends_on:
      - postgres
      - clickhouse
    networks:
      - app-network

  postgres:
    image: postgres:16
    environment:
      - POSTGRES_DB=langfuse
      - POSTGRES_USER=postgres
      - POSTGRES_PASSWORD=postgres
    volumes:
      - langfuse_postgres_data:/var/lib/postgresql/data
    networks:
      - app-network

  clickhouse:
    image: clickhouse/clickhouse-server:latest
    volumes:
      - langfuse_clickhouse_data:/var/lib/clickhouse
    networks:
      - app-network

volumes:
  langfuse_postgres_data:
  langfuse_clickhouse_data:

networks:
  app-network:
    driver: bridge
```

### Environment Variables in Docker

Create a `.env` file:

```bash
# Langfuse
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_BASE_URL=http://langfuse-web:3000
LANGFUSE_ENABLED=true

# Generate encryption key: openssl rand -hex 32
LANGFUSE_SALT=your_salt_here
LANGFUSE_ENCRYPTION_KEY=your_encryption_key_here

# OpenAI
OPENAI_API_KEY=sk-...
```

### Health Checks

```yaml
langfuse-web:
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:3000/api/public/health"]
    interval: 30s
    timeout: 10s
    retries: 3
```

---

## 10. Best Practices

### Trace ID Generation

**Deterministic Trace IDs** (Recommended for reproducibility):

```python
from langfuse import get_client

langfuse = get_client()
trace_seed = f"{session_id}-{user_id}-{message_hash}"
trace_id = langfuse.create_trace_id(seed=trace_seed)
```

**Random Trace IDs** (For unique traces):

```python
import uuid
trace_id = str(uuid.uuid4())
```

### Context Propagation

Always use `propagate_attributes()` at the top level of execution:

```python
trace_context = prepare_trace_context(
    user_id=user_id,
    session_id=session_id,
    metadata={"custom": "metadata"}
)

with propagate_attributes(**trace_context):
    # All traces within this context inherit user_id, session_id, metadata
    result = graph.invoke(state, config=config)
```

### Flushing Traces

**When to Flush**:
- After critical operations
- Before application shutdown
- In short-lived scripts
- After error handling

**When NOT to Flush**:
- In high-frequency operations (performance impact)
- Inside tight loops
- In background workers (let them flush periodically)

```python
# Good: Flush after operation
result = execute_agent(...)
flush_traces()
return result

# Good: Flush on error
try:
    result = execute_agent(...)
except Exception as e:
    flush_traces()  # Ensure error traces are sent
    raise

# Avoid: Flushing in loops
for item in items:
    process(item)
    flush_traces()  # Too frequent!
```

### Error Handling and Fallbacks

Always handle Langfuse failures gracefully:

```python
def get_callback_handler():
    if not LANGFUSE_ENABLED:
        return None
    
    try:
        return CallbackHandler()
    except Exception as e:
        logger.error(f"Failed to create CallbackHandler: {e}", exc_info=True)
        return None  # Continue without tracing
```

### Performance Considerations

1. **Async Tracing**: Langfuse sends traces asynchronously, minimal performance impact
2. **Batch Flushing**: Traces are batched automatically
3. **Disable in Development**: Use `LANGFUSE_ENABLED=false` for local development if needed
4. **Sampling**: Consider sampling for high-volume applications (advanced)

---

## 11. Common Patterns & Code Templates

### Generic Agent Base Class

```python
from abc import ABC, abstractmethod
from typing import List, Iterator
from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, AIMessage
from langchain_core.tools import BaseTool

class BaseAgent(ABC):
    def __init__(self, name: str, model: str = "gpt-4o-mini", temperature: float = 0.7):
        self.name = name
        self.llm = ChatOpenAI(
            model=model,
            temperature=temperature,
            streaming=True,
            stream_usage=True,
        )
    
    @abstractmethod
    def get_system_prompt(self) -> str:
        pass
    
    def get_tools(self) -> List[BaseTool]:
        return []
    
    def invoke(self, messages: List[BaseMessage], **kwargs) -> AIMessage:
        # Add system prompt
        system_prompt = self.get_system_prompt()
        if system_prompt:
            from langchain_core.messages import SystemMessage
            messages = [SystemMessage(content=system_prompt)] + messages
        
        # Bind tools
        tools = self.get_tools()
        llm_with_tools = self.llm.bind_tools(tools) if tools else self.llm
        
        # Pass config through
        invoke_kwargs = {}
        if 'config' in kwargs:
            invoke_kwargs['config'] = kwargs['config']
        
        return llm_with_tools.invoke(messages, **invoke_kwargs)
    
    def stream(self, messages: List[BaseMessage], **kwargs) -> Iterator[BaseMessage]:
        # Similar to invoke but yields chunks
        system_prompt = self.get_system_prompt()
        if system_prompt:
            from langchain_core.messages import SystemMessage
            messages = [SystemMessage(content=system_prompt)] + messages
        
        tools = self.get_tools()
        llm_with_tools = self.llm.bind_tools(tools) if tools else self.llm
        
        stream_kwargs = {}
        if 'config' in kwargs:
            stream_kwargs['config'] = kwargs['config']
        
        for chunk in llm_with_tools.stream(messages, **stream_kwargs):
            yield chunk
```

### Graph Node Implementation Pattern

```python
def your_node(state: YourState, config: dict = None) -> YourState:
    """
    Graph node implementation.
    
    Args:
        state: Current graph state
        config: Optional runtime config (contains callbacks from graph.invoke())
    """
    messages = state.get("messages", [])
    
    # Pass config to agent so callbacks propagate
    invoke_kwargs = {}
    if config:
        invoke_kwargs['config'] = config
    
    # Execute agent
    response = your_agent.invoke(messages, **invoke_kwargs)
    
    # Update state
    state["messages"].append(response)
    
    # Conditionally save (check execution_type)
    metadata = state.get("metadata", {})
    is_streaming = metadata.get("execution_type") == "streaming"
    
    if not is_streaming:
        save_message_to_db(response)
    
    return state
```

### Non-Streaming Function Template

```python
def execute_agent(user_id: int, session_id: int, message: str) -> dict:
    from langfuse import get_client, propagate_attributes
    from observability.tracing import (
        get_callback_handler,
        prepare_trace_context,
        flush_traces
    )
    
    # Generate trace ID
    langfuse = get_client() if LANGFUSE_ENABLED else None
    if langfuse:
        trace_seed = f"{session_id}-{user_id}-{uuid.uuid4()}"
        trace_id = langfuse.create_trace_id(seed=trace_seed)
    else:
        trace_id = str(uuid.uuid4())
    
    # Prepare config with callbacks
    config = {}
    callback_handler = get_callback_handler()
    if callback_handler:
        config['callbacks'] = [callback_handler]
    
    # Prepare trace context
    trace_context = prepare_trace_context(
        user_id=user_id,
        session_id=session_id,
        metadata={"execution_type": "graph", "trace_id": trace_id}
    )
    
    try:
        # Execute with context propagation
        with propagate_attributes(**trace_context):
            final_state = graph.invoke(initial_state, config=config)
        
        # Extract response
        response = final_state["messages"][-1].content
        
        flush_traces()
        
        return {"success": True, "response": response, "trace_id": trace_id}
    
    except Exception as e:
        logger.error(f"Error executing agent: {e}", exc_info=True)
        flush_traces()
        return {"success": False, "error": str(e), "trace_id": trace_id}
```

### Streaming Function Template

```python
def stream_agent_events(user_id: int, session_id: int, message: str) -> Iterator[dict]:
    from langfuse import get_client, propagate_attributes
    from observability.tracing import (
        get_callback_handler,
        prepare_trace_context,
        flush_traces
    )
    
    # Generate trace ID
    langfuse = get_client() if LANGFUSE_ENABLED else None
    if langfuse:
        trace_seed = f"{session_id}-{user_id}-{uuid.uuid4()}"
        trace_id = langfuse.create_trace_id(seed=trace_seed)
    else:
        trace_id = str(uuid.uuid4())
    
    # Prepare initial state (mark as streaming)
    initial_state = {
        "messages": messages,
        "metadata": {
            "execution_type": "streaming",  # Important!
            "trace_id": trace_id,
        }
    }
    
    # Prepare config with callbacks
    config = {}
    callback_handler = get_callback_handler()
    if callback_handler:
        config['callbacks'] = [callback_handler]
    
    # Prepare trace context
    trace_context = prepare_trace_context(
        user_id=user_id,
        session_id=session_id,
        metadata={"execution_type": "streaming", "trace_id": trace_id}
    )
    
    accumulated_content = ""
    
    try:
        # Stream with context propagation
        with propagate_attributes(**trace_context):
            for event in graph.stream(
                initial_state,
                config=config,
                stream_mode=["messages", "updates"]
            ):
                if isinstance(event, tuple) and len(event) == 2:
                    mode, data = event
                    
                    if mode == "messages":
                        message_chunk, metadata = data
                        if message_chunk and hasattr(message_chunk, 'content'):
                            content = message_chunk.content or ""
                            if content:
                                accumulated_content += content
                                yield {"type": "token", "data": content}
        
        # Save complete message after streaming
        save_message_to_db(accumulated_content)
        flush_traces()
        
        yield {"type": "done", "data": {"final_text": accumulated_content}}
    
    except Exception as e:
        logger.error(f"Error streaming agent: {e}", exc_info=True)
        flush_traces()
        yield {"type": "error", "data": {"error": str(e)}}
```

---

## 12. Troubleshooting

### Common Issues and Solutions

#### Issue: Traces Not Appearing in Langfuse UI

**Possible Causes**:
1. Environment variables not set correctly
2. Langfuse server not accessible
3. Traces not flushed
4. Network connectivity issues

**Solutions**:
```python
# Verify configuration
print(f"LANGFUSE_ENABLED: {LANGFUSE_ENABLED}")
print(f"LANGFUSE_PUBLIC_KEY: {LANGFUSE_PUBLIC_KEY[:10]}...")
print(f"LANGFUSE_BASE_URL: {LANGFUSE_BASE_URL}")

# Test connection
client = get_client()
if client:
    print("Client created successfully")
else:
    print("Failed to create client")

# Force flush
flush_traces()
```

#### Issue: Missing Trace Structure (Only Generations, No Chains)

**Cause**: Callbacks not propagated through graph nodes.

**Solution**: Ensure config is passed to all agent calls:

```python
# In nodes
def node(state, config=None):
    invoke_kwargs = {}
    if config:
        invoke_kwargs['config'] = config
    response = agent.invoke(messages, **invoke_kwargs)
```

#### Issue: Duplicate Messages in Database

**Cause**: Both nodes and streaming function saving messages.

**Solution**: Use `execution_type` in state metadata:

```python
# In streaming function
initial_state["metadata"]["execution_type"] = "streaming"

# In nodes
is_streaming = state["metadata"].get("execution_type") == "streaming"
if not is_streaming:
    save_message_to_db(response)
```

#### Issue: Performance Degradation

**Cause**: Flushing too frequently or synchronous operations.

**Solution**:
- Flush only after operations complete
- Use async tracing (default)
- Consider disabling in development

#### Issue: Connection Errors

**Cause**: Langfuse server not accessible or wrong URL.

**Solution**:
```python
# Verify URL
import requests
try:
    response = requests.get(f"{LANGFUSE_BASE_URL}/api/public/health", timeout=5)
    print(f"Langfuse health: {response.status_code}")
except Exception as e:
    print(f"Langfuse not accessible: {e}")
```

### Debugging Trace Creation

Enable debug logging:

```python
import logging
logging.getLogger("langfuse").setLevel(logging.DEBUG)
```

Check trace structure in Langfuse UI:
- Navigate to Traces section
- Click on a trace to see hierarchy
- Verify spans, chains, and generations are present

---

## 13. Advanced Topics

### Custom Spans and Observations

Create custom spans for operations outside LangChain:

```python
from langfuse import get_client

langfuse = get_client()

with langfuse.start_as_current_observation(
    as_type="span",
    name="Custom Operation",
    input={"data": "input"},
) as span:
    # Your custom operation
    result = perform_operation()
    
    span.update(output={"result": result})
```

### Metadata Enrichment

Add custom metadata to traces:

```python
trace_context = prepare_trace_context(
    user_id=user_id,
    session_id=session_id,
    metadata={
        "custom_field": "value",
        "environment": "production",
        "version": "1.0.0",
    }
)
```

### Filtering and Sampling

For high-volume applications, consider sampling:

```python
import random

def should_trace():
    return random.random() < 0.1  # Sample 10% of requests

if should_trace() and LANGFUSE_ENABLED:
    callback_handler = get_callback_handler()
else:
    callback_handler = None
```

### Multi-Tenant Tracing

Separate traces by tenant:

```python
trace_context = prepare_trace_context(
    user_id=user_id,
    session_id=session_id,
    metadata={
        "tenant_id": tenant_id,
        "organization_id": org_id,
    }
)
```

### Trace Aggregation

Use Langfuse API to aggregate traces:

```python
from langfuse import Langfuse

langfuse = Langfuse()

# Query traces
traces = langfuse.fetch_traces(
    project_id="your-project-id",
    limit=100
)
```

---

## 14. Metrics API & Analytics

### Overview

Langfuse provides two primary APIs for retrieving analytics and metrics:

- **Metrics API**: Aggregated analytics (token usage, costs) - optimized for performance
- **Observations API**: Raw observation data (agent/tool usage, detailed activity) - for detailed analysis

This section covers how to use these APIs to build custom statistics pages and analytics dashboards.

### API Versions: v1 vs v2

**Metrics API v2**:
- Available on Langfuse Cloud
- Optimized performance
- Direct aggregation
- Not available on self-hosted instances

**Observations API**:
- **v1**: Available on both Cloud and self-hosted
  - Requires querying traces first, then observations by trace ID
  - Limit: 100 observations per trace
- **v2**: Available on Langfuse Cloud only
  - Direct querying by session ID
  - Higher limits (1000+ observations)

**Our Implementation Strategy**:
1. Try Metrics API v2 first (if available)
2. Fallback to aggregating from Observations API v1 (self-hosted compatible)
3. Use Observations API v2 as secondary fallback (Cloud only)

### Querying Metrics

#### Basic Usage

```python
from app.services.langfuse_metrics import get_session_metrics_from_langfuse

# Get all metrics for a session
metrics = get_session_metrics_from_langfuse(session_id=123)

if metrics:
    print(f"Total tokens: {metrics['total_tokens']}")
    print(f"Total cost: ${metrics['cost']['total']}")
    print(f"Agent usage: {metrics['agent_usage']}")
    print(f"Tool usage: {metrics['tool_usage']}")
    print(f"Activity timeline: {len(metrics['activity_timeline'])} items")
```

#### Metrics API Query Structure

```python
from app.services.langfuse_metrics import build_metrics_query
from datetime import datetime

# Build query for Metrics API
query = build_metrics_query(
    session_id=123,
    from_timestamp=datetime.now()
)

# Query structure:
# {
#     "view": "observations",
#     "metrics": [
#         {"measure": "totalTokens", "aggregation": "sum"},
#         {"measure": "inputTokens", "aggregation": "sum"},
#         {"measure": "outputTokens", "aggregation": "sum"},
#         {"measure": "totalCost", "aggregation": "sum"},
#         {"measure": "inputCost", "aggregation": "sum"},
#         {"measure": "outputCost", "aggregation": "sum"},
#     ],
#     "filters": [
#         {
#             "column": "sessionId",
#             "operator": "=",
#             "value": "123",
#             "type": "string"
#         }
#     ],
#     "fromTimestamp": "2026-01-10T00:00:00.000Z",
#     "toTimestamp": "2026-01-10T23:59:59.999Z"
# }
```

### Querying Observations

#### Observations API v1 (Self-Hosted Compatible)

```python
from app.services.langfuse_metrics import query_session_observations
from langfuse import get_client
from datetime import datetime

langfuse = get_client()
observations = query_session_observations(
    langfuse_client=langfuse,
    session_id=123,
    from_timestamp=datetime.now()
)

# Observations are automatically converted to dictionaries
# Each observation includes '_trace_id' for grouping
for obs in observations:
    print(f"Type: {obs['type']}, Name: {obs['name']}")
    if obs.get('usage'):
        print(f"Tokens: {obs['usage'].get('total', 0)}")
```

#### Observations API v2 (Cloud Only)

The function automatically falls back to v2 if v1 fails:

```python
# Automatic fallback in query_session_observations()
# Uses filter parameter for v2:
filter_conditions = [
    {
        "type": "string",
        "column": "sessionId",
        "operator": "=",
        "value": "123"
    }
]
```

### Activity Timeline

The activity timeline provides a user-friendly view of all agent and tool interactions:

```python
from app.services.langfuse_metrics import format_observations_timeline

observations = query_session_observations(...)
timeline = format_observations_timeline(observations)

# Timeline items include:
# - id, trace_id, type, timestamp, latency_ms
# - tokens (input, output, total)
# - cost
# - category (llm_call, tool_call, event, other)
# - agent, tool, model (if applicable)
# - input_preview, output_preview (truncated to 200 chars)
```

#### Timeline Structure

```python
{
    'id': 'obs_123',
    'trace_id': 'trace_456',  # For grouping into message chains
    'type': 'GENERATION',
    'category': 'llm_call',
    'name': 'Greeter Agent',
    'agent': 'greeter',
    'timestamp': '2026-01-10T12:00:00Z',
    'latency_ms': 1234.5,
    'tokens': {
        'input': 100,
        'output': 50,
        'total': 150
    },
    'cost': 0.00015,
    'model': 'gpt-4o-mini',
    'input_preview': 'User message...',
    'output_preview': 'Agent response...'
}
```

### Handling Immutable Objects

Langfuse SDK v1 returns `ObservationsView` objects which are immutable. Our implementation automatically converts them:

```python
from app.services.langfuse_metrics import _convert_observation_to_dict

# Automatic conversion handles:
# - Pydantic models (.dict() method)
# - Objects with __dict__ attribute
# - Manual attribute extraction as fallback
# - Usage object conversion
# - Trace ID attachment for grouping

obs_dict = _convert_observation_to_dict(immutable_obs, trace_id="trace_123")
```

### Aggregating Metrics from Observations

When Metrics API is unavailable (self-hosted), metrics are aggregated from observations:

```python
from app.services.langfuse_metrics import _aggregate_metrics_from_observations

observations = query_session_observations(...)
metrics = _aggregate_metrics_from_observations(observations)

# Returns:
# {
#     "total_tokens": 1000,
#     "input_tokens": 700,
#     "output_tokens": 300,
#     "cached_tokens": 0,
#     "cost": {
#         "total": 0.001,
#         "input": 0.0007,
#         "output": 0.0003,
#         "cached": 0.0
#     }
# }
```

### Agent and Tool Usage Analytics

```python
from app.services.langfuse_metrics import aggregate_agent_tool_usage

observations = query_session_observations(...)
usage_stats = aggregate_agent_tool_usage(observations)

# Returns:
# {
#     "agent_usage": {
#         "greeter": 5,
#         "supervisor": 3
#     },
#     "tool_usage": {
#         "web_search": 2,
#         "database_query": 1
#     }
# }
```

#### Agent Identification

Agents are identified from:
1. Observation name (e.g., "greeter", "supervisor")
2. Trace name
3. Metadata fields (`agent_name`, `agentName`)

#### Tool Identification

Tools are identified from:
1. Tool calls in SPAN observation metadata
2. Observation name containing "tool" or "invoke"

### Complete Example: Session Statistics

```python
from app.services.langfuse_metrics import get_session_metrics_from_langfuse
from app.db.models.session import ChatSession

def get_session_stats(session_id: int):
    """Get comprehensive session statistics."""
    # Get message counts from database
    session = ChatSession.objects.get(id=session_id)
    messages = Message.objects.filter(session_id=session_id)
    
    # Get metrics from Langfuse
    langfuse_metrics = get_session_metrics_from_langfuse(session_id)
    if not langfuse_metrics:
        raise ValueError("Langfuse metrics unavailable")
    
    return {
        'session_id': session_id,
        'title': session.title,
        'total_messages': messages.count(),
        'user_messages': messages.filter(role='user').count(),
        'assistant_messages': messages.filter(role='assistant').count(),
        # From Langfuse
        'total_tokens': langfuse_metrics['total_tokens'],
        'input_tokens': langfuse_metrics['input_tokens'],
        'output_tokens': langfuse_metrics['output_tokens'],
        'cost': langfuse_metrics['cost'],
        'agent_usage': langfuse_metrics['agent_usage'],
        'tool_usage': langfuse_metrics['tool_usage'],
        'activity_timeline': langfuse_metrics['activity_timeline'],
    }
```

### Data Flow

```mermaid
graph TB
    Request[Session Stats Request] --> GetSession[Get Session from DB]
    GetSession --> QueryObs[Query Observations API]
    QueryObs --> TryMetrics[Try Metrics API v2]
    TryMetrics -->|Success| ExtractMetrics[Extract Metrics]
    TryMetrics -->|Fail| AggregateObs[Aggregate from Observations]
    QueryObs --> AggregateUsage[Aggregate Agent/Tool Usage]
    ExtractMetrics --> Combine[Combine Results]
    AggregateObs --> Combine
    AggregateUsage --> Combine
    QueryObs --> FormatTimeline[Format Activity Timeline]
    FormatTimeline --> Combine
    Combine --> Return[Return Statistics]
```

### Error Handling

```python
from app.services.langfuse_metrics import get_session_metrics_from_langfuse

try:
    metrics = get_session_metrics_from_langfuse(session_id)
    if not metrics:
        # Langfuse disabled or session has no traces
        return {"error": "Metrics unavailable"}
except Exception as e:
    logger.error(f"Failed to get metrics: {e}")
    return {"error": "Failed to retrieve metrics"}
```

### Performance Considerations

1. **Metrics API**: Fast, aggregated results (preferred when available)
2. **Observations API**: Slower, requires processing multiple traces
3. **Caching**: Consider caching results for frequently accessed sessions
4. **Pagination**: Observations API v1 has a limit of 100 per trace

### Troubleshooting

#### Issue: Metrics API Returns Zeros

**Symptoms**: `total_tokens: 0` despite observations existing

**Causes**:
- Metrics API not available (self-hosted)
- Observations not yet processed by Langfuse
- Time range mismatch

**Solution**: The function automatically falls back to observation aggregation.

#### Issue: ObservationsView is Immutable

**Symptoms**: `"ObservationsView" is immutable and does not support item assignment`

**Solution**: Our `_convert_observation_to_dict()` function handles this automatically.

#### Issue: No Observations Returned

**Causes**:
- Session has no traces
- Traces exist but have no observations
- API version mismatch

**Debugging**:
```python
# Check if traces exist
traces = langfuse.api.trace.list(session_id=str(session_id))
print(f"Found {len(traces)} traces")

# Check observations per trace
for trace in traces:
    obs = langfuse.api.observations.get_many(trace_id=trace.id)
    print(f"Trace {trace.id}: {len(obs)} observations")
```

#### Issue: Activity Timeline Empty

**Causes**:
- Observations not properly converted
- Trace ID not attached
- Filtering issues

**Solution**: Ensure observations are converted to dicts with `_trace_id` attached.

### Best Practices

1. **Use Metrics API when available**: Faster and more efficient
2. **Fallback gracefully**: Always have observation aggregation as fallback
3. **Handle timezones**: Always use UTC for timestamps
4. **Group by trace_id**: Use trace_id to group activities into message chains
5. **Limit observation queries**: Use appropriate limits (100 for v1, 1000 for v2)
6. **Cache results**: Consider caching for frequently accessed sessions
7. **Error handling**: Always handle cases where Langfuse is unavailable

### Code Organization

The metrics service is organized into:

- **Helper Functions** (private, `_` prefix): Data extraction and conversion
- **Public API Functions**: Main entry points
- **Timeline Formatting**: User-friendly activity display

```python
# Helper functions
_normalize_api_response()
_extract_trace_ids()
_convert_observation_to_dict()
_extract_usage_data()
_extract_cost_data()
_aggregate_metrics_from_observations()

# Public API
build_metrics_query()
query_session_observations()
extract_metrics_from_response()
aggregate_agent_tool_usage()
get_session_metrics_from_langfuse()

# Timeline
format_observations_timeline()
```

---

## 15. Maintenance & Updates

### How to Update This Guide

1. **When Learning New Patterns**: Add new sections or update existing ones
2. **When Discovering Issues**: Add to Troubleshooting section
3. **When SDK Updates**: Update version numbers and breaking changes
4. **When Best Practices Change**: Update relevant sections

### Version Compatibility Notes

| Component | Version | Notes |
|-----------|---------|-------|
| Langfuse SDK | >=3.0.0 | Uses OpenTelemetry |
| LangChain | >=0.1.0 | Latest stable |
| LangGraph | >=0.0.40 | Checkpoint support required |
| Django | >=5.0.0 | Tested with 5.0+ |

### Breaking Changes Tracking

**SDK v2 → v3**:
- `Langfuse()` constructor → `get_client()`
- Manual key passing → Environment variables
- Different callback handler API

### Migration Guides

When migrating from other tracing solutions:

1. **From LangSmith**: Replace `LangSmithCallbackHandler` with `CallbackHandler`
2. **From Custom Tracing**: Use `propagate_attributes()` for context
3. **From SDK v2**: Update to `get_client()` pattern

### Contribution Guidelines

When contributing to this guide:

1. Keep examples generic and reusable
2. Include both simple and complex patterns
3. Add diagrams for complex flows
4. Test examples before adding
5. Update version numbers and dates

---

## Quick Reference

### Essential Functions

```python
# Client
get_langfuse_client()  # Get singleton client

# Callbacks
get_callback_handler()  # Get CallbackHandler for LangChain

# Context
prepare_trace_context(user_id, session_id, metadata)  # Prepare context dict
propagate_attributes(**trace_context)  # Context manager

# Lifecycle
flush_traces()  # Flush pending traces
shutdown_client()  # Graceful shutdown
```

### Essential Patterns

```python
# Non-streaming
with propagate_attributes(**trace_context):
    result = graph.invoke(state, config={"callbacks": [handler]})
flush_traces()

# Streaming
with propagate_attributes(**trace_context):
    for event in graph.stream(state, config={"callbacks": [handler]}, stream_mode=["messages", "updates"]):
        # Process events
flush_traces()

# Node implementation
def node(state, config=None):
    invoke_kwargs = {"config": config} if config else {}
    response = agent.invoke(messages, **invoke_kwargs)
    return state
```

---

## Additional Resources

- [Langfuse Documentation](https://langfuse.com/docs)
- [LangChain Documentation](https://python.langchain.com/)
- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [OpenAI API Documentation](https://platform.openai.com/docs)

---

**Remember**: This is a living document. Update it as you learn and discover new patterns!
