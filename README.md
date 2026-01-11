# 🤖 Agent Playground

> **The Production-Ready Multi-Agent Platform Built on LangGraph Functional API**

> **A battle-tested, enterprise-grade platform for building, deploying, and scaling sophisticated AI agent systems with real-time observability, intelligent routing, and complete RAG capabilities.**

Agent Playground is a comprehensive full-stack platform that transforms how you build AI agent applications. Unlike experimental frameworks or proof-of-concepts, this is a **production-ready system** built on LangGraph's cutting-edge Functional API architecture, providing type-safe task composition, real-time streaming, and complete observability out of the box.

**Built for developers who need more than a prototype** - this platform delivers enterprise-grade features including multi-agent orchestration, persistent state management, cost tracking, and a beautiful real-time UI that rivals commercial solutions.

---

## 🎯 Why Agent Playground?

Building production AI agent systems is complex. You need:
- **Multi-agent orchestration** with intelligent routing
- **Full observability** to understand what your agents are doing
- **Cost tracking** to monitor token usage and expenses
- **RAG capabilities** for knowledge-enhanced agents
- **State persistence** for conversational memory
- **Production-ready infrastructure** that scales

Agent Playground provides all of this out of the box, with a beautiful UI, comprehensive APIs, and battle-tested architecture.

---

## 💎 What Makes This Different?

**Not Another Prototype** - This is a production-ready system that's been architected for real-world deployment:

- **LangGraph Functional API**: Built on the latest Functional API with `@entrypoint` and `@task` decorators for clean, type-safe, maintainable code
- **Real-Time Everything**: Live token streaming, task status updates, and tool execution visibility - not just final results
- **Complete Observability**: Every LLM call, tool invocation, and agent decision traced with Langfuse - see exactly what's happening
- **Type-Safe Architecture**: Pydantic models ensure data integrity and catch errors at development time, not production
- **Production Infrastructure**: Multi-tenant architecture, persistent state, error handling, and scalability built-in
- **Full Stack Solution**: Beautiful React frontend, comprehensive Django API, and complete deployment setup - no assembly required

**Compare to alternatives**: Most agent frameworks are experimental or require significant customization. Agent Playground is a complete, production-ready platform that works out of the box while remaining fully extensible.

---

## 🚀 Why This Matters

**Production-Ready vs. Prototype**: While many projects demonstrate concepts, Agent Playground is architected for real-world deployment with proper error handling, state persistence, observability, and scalability.

**Real-World Use Cases**:
- **Enterprise Knowledge Assistants**: RAG-powered agents that search through company documents
- **Customer Support Systems**: Multi-agent routing for different support scenarios
- **Research Platforms**: Agents that can search, analyze, and synthesize information
- **Internal Tools**: Specialized agents for different departments or workflows

**Developer Experience**: The Functional API architecture makes it easy to understand, extend, and maintain. Tasks are clearly defined, type-safe, and composable.

**Cost Efficiency**: Built-in observability means you can track and optimize costs from day one, not after deployment.

**Scalability**: PostgreSQL-backed state persistence, efficient checkpointing, and proper architecture ensure the system scales with your needs.

---

## ✨ Key Features

### 🏗️ LangGraph Functional API Architecture
- **Modern Task-Based System**: Built on LangGraph's Functional API with `@entrypoint` and `@task` decorators
- **Type-Safe by Design**: Pydantic models ensure data integrity and catch errors early
- **Clean Composition**: Tasks are modular, testable, and easily composable
- **Better Maintainability**: Functional approach makes code easier to understand and extend
- **Natural Flow**: Task-based workflow mirrors how agents actually work
- **Comprehensive Documentation**: See `docs/LANGGRAPH_FUNCTIONAL_API_LESSONS_LEARNED.md` for deep technical insights

### 🧠 Multi-Agent System (LangGraph Functional API)
- **Supervisor Pattern**: Intelligent routing via `supervisor_task` that analyzes intent and routes to specialized agents
- **Task-Based Agents**: Each agent is a `@task` function (`greeter_agent_task`, `search_agent_task`) with clear inputs/outputs
- **Extensible Architecture**: Add new agents by creating new `@task` functions - no complex graph definitions
- **State Management**: Persistent conversation state with PostgreSQL checkpoints via `PostgresSaver`
- **Tool Framework**: Dynamic tool registration with automatic execution via `tool_execution_task`
- **Streaming Support**: Real-time token streaming with SSE, plus live task status updates

### 📡 Real-Time Streaming & Status Updates
- **Token Streaming**: Real-time LLM token delivery via Server-Sent Events (SSE)
- **Task Status Updates**: Live visibility into workflow progress:
  - "Loading conversation history..."
  - "Routing to agent..."
  - "Processing with search agent..."
  - "Executing tools..."
  - "Processing tool results..."
- **Tool Execution Visibility**: See tools being executed in real-time with status transitions
- **Ephemeral UI State**: Status messages are ephemeral (not persisted) for clean, real-time feedback
- **Stream Completion Tracking**: Tool items and final results appear only after stream completes

### 📊 Full Observability (Langfuse v3)
- **Complete Tracing**: Track every LLM call, tool invocation, and agent decision with full context
- **Token Analytics**: Real-time tracking of input, output, and cached tokens per operation
- **Cost Monitoring**: Automatic cost calculation per model, session, agent, and tool
- **Activity Timeline**: Visualize complete agent execution flows with hierarchical task breakdown
- **Debugging Tools**: Inspect inputs, outputs, and intermediate steps for every operation
- **Self-Hosted or Cloud**: Deploy Langfuse locally (included in Docker Compose) or use Langfuse Cloud

### 🔍 RAG (Retrieval-Augmented Generation)
- **Vector Search**: PostgreSQL with pgvector for high-performance semantic search
- **Document Ingestion**: Upload and process documents (PDF, Markdown, Plain Text) with automatic chunking
- **Enhanced PDF Processing**: 
  - Multiple extraction backends (pdfplumber, PyMuPDF, pypdf) with automatic fallback
  - OCR support for scanned PDFs via Tesseract
  - Table extraction and preservation
  - Layout-aware text extraction
- **Advanced Chunking**: 
  - Semantic chunking that preserves sentence boundaries
  - Accurate token counting with tiktoken
  - Configurable strategies (recursive or semantic)
- **Multi-tenant Isolation**: Secure, user-scoped document access at the database level
- **RAG Tool Integration**: Fully implemented `rag_retrieval_tool` for agents to search documents

### 💰 Cost & Token Tracking
- **Real-time Tracking**: Monitor tokens during streaming responses with live updates
- **Granular Breakdown**: Separate tracking for input, output, cached, and total tokens
- **Model-based Pricing**: Configurable pricing per model with automatic cost calculation
- **Session Analytics**: Per-session and per-user statistics with detailed breakdowns
- **Cost Attribution**: Track costs by agent, tool, user, and operation type

### 🔐 Production-Ready Features
- **Multi-user Authentication**: JWT-based auth with refresh tokens and secure session management
- **Multi-tenant Architecture**: Complete user isolation at database level with proper security
- **RESTful API**: Comprehensive API with proper error handling, validation, and documentation
- **Hot Reload**: Development mode with automatic code reloading for rapid iteration
- **Docker Compose**: One-command deployment for all services (backend, frontend, database, Langfuse)
- **Error Handling**: Comprehensive error handling with graceful degradation and logging
- **Connection Resilience**: Automatic checkpointer reconnection for production reliability

---

## 🏗️ Technology Stack

### Backend
- **Django 5.0+**: Robust web framework with REST API and admin interface
- **LangChain 0.1.0+**: Core LLM orchestration and tool integration
- **LangGraph 0.0.40+**: Multi-agent state machine with **Functional API** (`@entrypoint`, `@task`)
- **LangGraph Checkpoint Postgres 2.0.0+**: PostgreSQL-backed state persistence
- **Pydantic**: Type-safe data models for request/response validation
- **Langfuse 3.0.0+**: AI observability and tracing (OpenTelemetry-based)
- **PostgreSQL 16 + pgvector**: Vector database for RAG with semantic search
- **Django REST Framework 3.14.0+**: RESTful API with JWT authentication
- **PDF Processing**: 
  - pdfplumber 0.10.0+ (layout-aware extraction, table support)
  - PyMuPDF 1.23.0+ (fast extraction)
  - pypdf 3.0.0+ (fallback)
- **OCR**: pytesseract 0.3.10+ + pdf2image 1.16.0+ for scanned PDF support
- **Token Counting**: tiktoken 0.5.0+ for accurate token estimation
- **NLP**: spaCy 3.7.0+ (optional) for semantic chunking

### Frontend
- **React 18**: Modern UI library
- **Vite**: Fast build tool and dev server
- **TypeScript**: Type-safe development
- **Tailwind CSS**: Utility-first styling
- **shadcn/ui**: High-quality component library
- **Zustand**: Lightweight state management
- **Axios**: HTTP client with interceptors

### Infrastructure
- **Docker & Docker Compose**: Containerized deployment
- **Nginx**: Reverse proxy (optional)
- **Langfuse Server**: Self-hosted observability (included in compose)
- **Redis**: Caching and queue management (for Langfuse)
- **ClickHouse**: Analytics database (for Langfuse)
- **MinIO**: S3-compatible object storage (for Langfuse)

---

## 🚀 Quick Start

### Prerequisites

- **Docker** and **Docker Compose** (latest version)
- **Git** (optional, for cloning)

> **Note for Windows Users**: The Makefile uses Unix commands. On Windows, use `docker-compose` commands directly (see [Windows Support](#-windows-support) below).

### Installation

1. **Clone the repository** (or download):
   ```bash
   git clone <repository-url>
   cd Agent-Playground
   ```

2. **Create environment file**:
   ```bash
   # Windows (PowerShell)
   Copy-Item .env.example .env
   
   # macOS/Linux
   cp .env.example .env
   ```

3. **Configure environment variables**:
   Edit `.env` and add your API keys:
   ```env
   # Required: OpenAI API Key
   OPENAI_API_KEY=your_openai_api_key_here
   OPENAI_MODEL=gpt-4o-mini
   
   # Optional: Langfuse (for observability)
   LANGFUSE_ENABLED=true
   LANGFUSE_PUBLIC_KEY=your_public_key
   LANGFUSE_SECRET_KEY=your_secret_key
   LANGFUSE_BASE_URL=http://localhost:3001
   
   # Database (defaults work for local dev)
   DB_NAME=ai_agents_db
   DB_USER=postgres
   DB_PASSWORD=postgres
   ```

4. **Start all services**:
   ```bash
   # Using docker-compose (works on all platforms)
   docker-compose up -d
   
   # Or using make (macOS/Linux only)
   make up
   ```

5. **Run database migrations**:
   ```bash
   # Using docker-compose
   docker-compose exec backend python manage.py migrate
   
   # Or using make
   make migrate
   ```

6. **Create a superuser** (optional):
   ```bash
   # Interactive
   docker-compose exec backend python manage.py createsuperuser
   
   # Non-interactive (Windows-friendly)
   docker-compose exec backend python create_superuser.py admin@example.com yourpassword
   ```

7. **Access the application**:
   - **Frontend**: http://localhost:3000
   - **Backend API**: http://localhost:8000
   - **API Docs**: http://localhost:8000/api/docs/ (if enabled)
   - **Django Admin**: http://localhost:8000/admin/
   - **Langfuse UI**: http://localhost:3001 (if enabled)

8. **Try your first interaction**:
   - Open http://localhost:3000 and create an account or log in
   - Start a new chat session
   - Send a message like "Hello!" or "What can you help me with?"
   - Watch the real-time status updates as the system:
     - Loads conversation history
     - Routes to the appropriate agent (supervisor)
     - Processes with the selected agent
     - Streams the response token by token
   - Check Langfuse UI (http://localhost:3001) to see the complete execution trace
   - Upload a document and ask questions about it to see RAG in action

---

## 🪟 Windows Support

On Windows, `make` is not available by default. Use `docker-compose` commands directly:

| Make Command | Docker Compose Equivalent |
|-------------|---------------------------|
| `make up` | `docker-compose up -d` |
| `make down` | `docker-compose down` |
| `make build` | `docker-compose build` |
| `make logs` | `docker-compose logs -f` |
| `make migrate` | `docker-compose exec backend python manage.py migrate` |
| `make shell-backend` | `docker-compose exec backend bash` |
| `make shell-db` | `docker-compose exec db psql -U postgres -d ai_agents_db` |
| `make test` | `docker-compose exec backend python manage.py test` |

Alternatively, install `make` via:
- **Chocolatey**: `choco install make`
- **WSL**: Use Windows Subsystem for Linux

---

## 📖 Architecture

### System Overview

```
┌─────────────────────────────────────────────────────────────┐
│                      Frontend (React)                        │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
│  │   Chat   │  │  Stats   │  │ Profile  │  │  Docs    │  │
│  │ (SSE)    │  │          │  │          │  │          │  │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘  │
└──────────────────────┬──────────────────────────────────────┘
                       │ HTTP/SSE (Real-time Streaming)
┌──────────────────────┴──────────────────────────────────────┐
│              Django REST API (Backend)                       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │   Auth API   │  │   Chat API   │  │  Agent API   │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │    LangGraph Functional API (@entrypoint workflow)    │  │
│  │                                                       │  │
│  │  @entrypoint → ai_agent_workflow                     │  │
│  │       │                                              │  │
│  │       ├─→ @task load_messages_task                   │  │
│  │       ├─→ @task supervisor_task                      │  │
│  │       │       └─→ Routes to agent                    │  │
│  │       ├─→ @task greeter_agent_task                  │  │
│  │       ├─→ @task search_agent_task                   │  │
│  │       ├─→ @task tool_execution_task                 │  │
│  │       ├─→ @task agent_with_tool_results_task        │  │
│  │       └─→ @task save_message_task                    │  │
│  │                                                       │  │
│  │  Streaming: BaseCallbackHandler → SSE Events         │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │   LangChain  │  │   Langfuse   │  │     RAG       │    │
│  │   (LLM)      │  │ (Tracing)    │  │  (Vector DB)  │    │
│  └──────────────┘  └──────────────┘  └──────────────┘    │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────┴──────────────────────────────────────┐
│                    Infrastructure Layer                       │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐    │
│  │PostgreSQL│  │  Redis   │  │ClickHouse│  │  MinIO   │    │
│  │+pgvector │  │          │  │          │  │          │    │
│  │(Checkpoint)│ │          │  │          │  │          │    │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘    │
└─────────────────────────────────────────────────────────────┘
```

### Backend Architecture

#### Agent System - Functional API (`app/agents/`)

**LangGraph Functional API Architecture** - Built with `@entrypoint` and `@task` decorators for clean, type-safe, composable workflows.

```
agents/
├── functional/           # Functional API implementation
│   ├── workflow.py      # @entrypoint ai_agent_workflow
│   ├── tasks.py         # @task functions (supervisor, agents, tools)
│   ├── models.py        # Pydantic models (AgentRequest, AgentResponse)
│   └── middleware.py    # LangChain middleware setup
├── agents/              # Agent implementations (used by tasks)
│   ├── base.py         # BaseAgent abstract class
│   ├── supervisor.py   # Routing agent
│   ├── greeter.py      # Welcome agent
│   └── search.py       # RAG-powered search agent
├── tools/               # Agent tools
│   ├── base.py         # BaseTool interface
│   ├── registry.py     # Tool registration system
│   └── rag_tool.py     # RAG retrieval tool (IMPLEMENTED)
├── checkpoint.py        # PostgreSQL checkpoint adapter
├── config.py            # Agent configuration
└── runner.py            # Workflow execution & streaming
```

**Key Components:**
- **@entrypoint Workflow**: Main `ai_agent_workflow` function orchestrates the entire flow
- **@task Functions**: Modular, composable tasks for each operation:
  - `supervisor_task` - Intelligent routing
  - `load_messages_task` - Conversation history loading
  - `greeter_agent_task` / `search_agent_task` - Specialized agents
  - `tool_execution_task` - Tool orchestration
  - `agent_with_tool_results_task` - Result processing
  - `save_message_task` - Persistence
- **Pydantic Models**: Type-safe request/response with validation
- **PostgreSQL Checkpoints**: Persistent state via `PostgresSaver` with connection resilience
- **Streaming**: Real-time token streaming via `BaseCallbackHandler` with SSE
- **Task Composition**: Tasks naturally compose - output of one becomes input to next

#### Observability (`app/observability/`)
- **Langfuse v3 SDK**: OpenTelemetry-based tracing
- **Automatic Instrumentation**: LangChain callback handlers
- **Trace Context**: User and session metadata propagation
- **Metrics API**: Token usage, costs, and performance metrics

#### RAG System (`app/rag/`)
- **Document Processing**: Upload, chunking, and embedding
  - **Enhanced PDF Extraction**: Multiple backends (pdfplumber, PyMuPDF, pypdf) with automatic fallback
  - **OCR Support**: Automatic detection and OCR processing for scanned PDFs
  - **Table Extraction**: Preserves tables from PDFs when using pdfplumber
  - **Layout-Aware**: Better text extraction with structure preservation
- **Advanced Chunking**: 
  - **Semantic Chunking**: Preserves sentence and paragraph boundaries
  - **Accurate Token Counting**: Uses tiktoken for precise token estimation
  - **Configurable Strategies**: Choose between recursive or semantic chunking
- **Vector Store**: pgvector for semantic search
- **Retriever**: User-scoped context retrieval
- **Multi-tenant**: Complete user isolation

### Frontend Architecture

```
src/
├── app/                 # Page components
│   ├── chat/           # Chat interface with real-time streaming
│   │   └── ChatPage.tsx  # Main chat with status updates
│   ├── auth/           # Authentication
│   └── DashboardPage   # Main dashboard
├── components/          # Reusable components
│   ├── ui/             # shadcn/ui components
│   ├── MarkdownMessage # Message rendering
│   ├── PlanProposal    # Plan visualization
│   └── JsonViewer      # Tool result display
├── state/               # Zustand stores
│   ├── useAuthStore    # Authentication state
│   └── useChatStore    # Chat state with message management
└── lib/                 # Utilities
    ├── api.ts          # API client with interceptors
    └── streaming.ts    # SSE streaming handler
```

**Key Features:**
- **Real-Time Streaming**: SSE-based token streaming with live updates
- **Status Updates**: Ephemeral status messages showing task progress
- **Tool Visibility**: Collapsible tool execution details after stream completes
- **State Management**: Zustand with proper message merging and persistence
- **Type Safety**: Full TypeScript coverage with proper types

---

## 🏗️ LangGraph Functional API Deep Dive

### What is LangGraph Functional API?

The Functional API is LangGraph's modern approach to building agent workflows using Python decorators (`@entrypoint` and `@task`) instead of traditional graph definitions. This provides:

- **Type Safety**: Pydantic models ensure data integrity
- **Cleaner Code**: Functions instead of graph nodes
- **Better Testing**: Each task is independently testable
- **Natural Composition**: Tasks compose naturally - output of one becomes input to next
- **IDE Support**: Full autocomplete and type checking

### Why Functional API Over Graph-Based?

**Traditional Graph Approach** (what we replaced):
- Complex graph definitions with nodes and edges
- TypedDict state management
- Conditional routing via separate router functions
- Harder to test individual components
- More boilerplate code

**Functional API Approach** (current):
- Simple `@task` decorators on functions
- Pydantic models for type safety
- Natural function composition
- Each task is a pure function (easier to test)
- Less boilerplate, more readable

### Key Components

#### 1. Entrypoint (`@entrypoint`)

The main workflow function that orchestrates everything:

```python
@entrypoint(checkpointer=_checkpointer_instance)
def ai_agent_workflow(request: AgentRequest) -> AgentResponse:
    """Main entrypoint for AI agent workflow."""
    # Task composition happens here
    messages = load_messages_task(...)
    routing = supervisor_task(...)
    response = agent_task(...)
    save_message_task(...)
    return response
```

#### 2. Tasks (`@task`)

Individual operations as decorated functions:

```python
@task
def supervisor_task(
    query: str,
    messages: List[BaseMessage],
    config: Optional[RunnableConfig] = None
) -> RoutingDecision:
    """Route user query to appropriate agent."""
    # Implementation
    return RoutingDecision(agent="search", query=query)
```

#### 3. Pydantic Models

Type-safe request/response models:

```python
class AgentRequest(BaseModel):
    query: str
    session_id: Optional[int] = None
    user_id: Optional[int] = None
    flow: str = "main"

class AgentResponse(BaseModel):
    type: Literal["answer", "plan_proposal"] = "answer"
    reply: Optional[str] = None
    tool_calls: List[Dict[str, Any]] = []
    agent_name: Optional[str] = None
```

#### 4. State Management

PostgreSQL-backed checkpoints via `PostgresSaver`:

- Persistent conversation state
- Automatic checkpointing between tasks
- Connection resilience with automatic reconnection
- Thread-based isolation per session

### Task Flow Example

When a user sends "What is Madde 10 according to docs?":

1. **`load_messages_task`**: Loads conversation history from checkpoint/DB
2. **`supervisor_task`**: Analyzes query, routes to "search" agent
3. **`search_agent_task`**: Processes query, identifies need for RAG tool
4. **`tool_execution_task`**: Executes `rag_retrieval_tool` with query="Madde 10"
5. **`agent_with_tool_results_task`**: Processes tool results, generates final response
6. **`save_message_task`**: Persists response with metadata to database

All tasks are traced in Langfuse, and status updates are streamed to the frontend in real-time.

### Streaming with Functional API

Unlike `astream_events()` (which requires async checkpoints), we use:

- **`stream()` method**: Works with sync `PostgresSaver`
- **`BaseCallbackHandler`**: Captures LLM tokens via `on_llm_new_token`
- **Task Status**: Captures task start/end via `on_chain_start` / `on_chain_end`
- **Tool Status**: Captures tool execution via `on_tool_start` / `on_tool_end`

This provides real-time streaming while maintaining compatibility with PostgreSQL checkpoints.

### Error Handling & Resilience

- **Checkpointer Wrapper**: Automatic reconnection if database connection drops
- **Graceful Degradation**: Falls back to database if checkpoint fails
- **Error Propagation**: Errors are caught, logged, and returned in response
- **Django Auto-Reload**: Handles development server reloads gracefully

### Learn More

For comprehensive technical details, implementation patterns, and lessons learned, see:
- **[LangGraph Functional API Lessons Learned](./docs/LANGGRAPH_FUNCTIONAL_API_LESSONS_LEARNED.md)** - Deep technical dive with code examples

---

## 🔧 Development

### Backend Development

```bash
# Open backend shell
docker-compose exec backend bash

# Create new migrations
docker-compose exec backend python manage.py makemigrations

# Run migrations
docker-compose exec backend python manage.py migrate

# Run tests
docker-compose exec backend python manage.py test

# Access Django shell
docker-compose exec backend python manage.py shell
```

### Frontend Development

The frontend runs in development mode with hot-reload enabled. Changes are automatically reflected.

```bash
# Access frontend container (if needed)
docker-compose exec frontend sh

# Frontend runs automatically via Docker Compose
# Edit files in frontend/src/ and see changes instantly
```

### Database Access

```bash
# Open PostgreSQL shell
docker-compose exec db psql -U postgres -d ai_agents_db

# Or using make (macOS/Linux)
make shell-db
```

### Adding a New Agent (Functional API)

With the Functional API, adding a new agent is straightforward:

1. **Create agent class** in `backend/app/agents/agents/`:
   ```python
   from app.agents.agents.base import BaseAgent
   
   class MyAgent(BaseAgent):
       def __init__(self):
           super().__init__(
               name="my_agent",
               description="Does something specific"
           )
       
       def get_system_prompt(self) -> str:
           return "You are a helpful assistant that..."
       
       def get_tools(self) -> List[BaseTool]:
           # Return agent-specific tools
           return []
   ```

2. **Create agent task** in `backend/app/agents/functional/tasks.py`:
   ```python
   @task
   def my_agent_task(
       request: AgentRequest,
       routing: RoutingDecision,
       messages: List[BaseMessage],
       config: Optional[RunnableConfig] = None
   ) -> AgentResponse:
       """Process query with my agent."""
       my_agent = MyAgent()
       # Use agent to process query
       # Return AgentResponse
   ```

3. **Register in supervisor** (`backend/app/agents/agents/supervisor.py`):
   ```python
   AVAILABLE_AGENTS = {
       # ... existing agents
       "my_agent": "Description of what my agent does",
   }
   ```

4. **Add to workflow** (`backend/app/agents/functional/workflow.py`):
   ```python
   # In ai_agent_workflow, add routing case:
   if routing.agent == "my_agent":
       response = my_agent_task(request, routing, messages, config)
   ```

### Adding a New Tool

1. **Create tool class** in `backend/app/agents/tools/`:
   ```python
   from app.agents.tools.base import AgentTool
   from langchain_core.tools import tool
   
   class MyTool(AgentTool):
       @property
       def name(self) -> str:
           return "my_tool"
       
       @property
       def description(self) -> str:
           return "Tool description"
       
       def get_tool(self) -> BaseTool:
           @tool
           def my_tool_function(query: str) -> str:
               """Tool function docstring."""
               # Implementation
               return result
           return my_tool_function
   ```

2. **Register in registry** (`backend/app/agents/tools/registry.py`):
   ```python
   from app.agents.tools.my_tool import MyTool
   
   # Register in ToolRegistry
   registry.register(MyTool())
   ```

3. **Tool is automatically available** - The `tool_execution_task` will discover and execute it when agents propose tool calls.

### Creating a New Task

Tasks are the building blocks of the Functional API workflow:

```python
from langgraph.func import task
from app.agents.functional.models import AgentRequest, AgentResponse

@task
def my_custom_task(
    request: AgentRequest,
    some_input: str,
    config: Optional[RunnableConfig] = None
) -> Dict[str, Any]:
    """
    Custom task that does something specific.
    
    Args:
        request: Agent request with query and context
        some_input: Some input data
        config: Optional runtime config for callbacks
        
    Returns:
        Dictionary with task results
    """
    # Task implementation
    result = do_something(request.query, some_input)
    return {"result": result}
```

Then use it in the workflow:

```python
@entrypoint(checkpointer=_checkpointer_instance)
def ai_agent_workflow(request: AgentRequest) -> AgentResponse:
    # ... existing tasks
    custom_result = my_custom_task(request, "some_value")
    # Use custom_result in subsequent tasks
    # ...
```

---

## 📊 Features in Detail

### Multi-Agent System (Functional API)

**Supervisor Pattern with Task-Based Architecture**: The `supervisor_task` intelligently routes user messages to specialized agent tasks based on context and intent.

**Task Flow:**
1. **`supervisor_task`**: Analyzes user query and conversation history, returns `RoutingDecision`
2. **Agent Tasks**: Based on routing decision:
   - **`greeter_agent_task`**: Handles initial interactions, provides guidance, welcomes users
   - **`search_agent_task`**: RAG-powered agent that searches user documents and answers questions
3. **Tool Execution**: If agent proposes tools, `tool_execution_task` executes them
4. **Result Processing**: `agent_with_tool_results_task` processes tool outputs and generates final response

**Current Agents:**
- **Supervisor** (`supervisor_task`): Routes messages to appropriate agents using LLM-based intent analysis
- **Greeter** (`greeter_agent_task`): Handles initial interactions, provides guidance, explains capabilities
- **Search** (`search_agent_task`): **IMPLEMENTED** - RAG-powered agent that:
  - Searches through user's uploaded documents
  - Uses `rag_retrieval_tool` to retrieve relevant context
  - Answers questions based on document content
  - Provides citations and document references

**Extensibility**: Adding new agents is straightforward:
1. Create agent class (inherit from `BaseAgent`)
2. Create `@task` function for the agent
3. Register in supervisor's `AVAILABLE_AGENTS`
4. Add routing case in workflow

**Type Safety**: All tasks use Pydantic models (`AgentRequest`, `AgentResponse`, `RoutingDecision`) ensuring type safety and validation.

### Observability with Langfuse

**Complete Tracing**: Every LLM call, tool invocation, and agent decision is traced with full context.

**Key Capabilities:**
- **Trace Hierarchy**: See complete execution flows from top-level traces to individual spans
- **Token Tracking**: Real-time input/output/cached token counts
- **Cost Attribution**: Track costs by agent, tool, and user
- **Activity Timeline**: Visualize agent execution with detailed timelines
- **Debugging**: Inspect inputs, outputs, and intermediate steps

**Self-Hosted**: Langfuse server is included in Docker Compose, or use Langfuse Cloud.

### RAG (Retrieval-Augmented Generation)

**Document Processing**:
- Upload documents via API or UI (PDF, Markdown, Plain Text)
- **Enhanced PDF Extraction**:
  - Multiple extraction backends: pdfplumber (layout-aware, table support), PyMuPDF (fast), pypdf (fallback)
  - Automatic fallback chain for reliability
  - OCR support for scanned/image-based PDFs (via Tesseract)
  - Table extraction and preservation
- **Advanced Chunking**:
  - **Semantic Chunking**: Preserves sentence and paragraph boundaries, avoids mid-sentence splits
  - **Accurate Token Counting**: Uses tiktoken for precise token estimation (replaces rough character estimation)
  - **Configurable Strategies**: Choose between recursive or semantic chunking via settings
  - **PDF-Optimized**: Handles page breaks, paragraphs, and document structure
- Automatic embedding and vector storage in PostgreSQL with pgvector

**Retrieval**:
- Semantic search with similarity scoring
- User-scoped queries (multi-tenant isolation)
- Configurable result limits and thresholds
- Reranking support for improved relevance

**Status**: Core infrastructure is in place. RAG tool integration for agents is implemented and working.

### Cost & Token Tracking

**Real-time Tracking**:
- Token counts during streaming responses
- Separate tracking for input, output, and cached tokens
- Automatic aggregation per message, session, and user

**Cost Calculation**:
- Model-based pricing configuration
- Automatic cost calculation from token usage
- Per-session and per-user cost analytics

**Configuration**: Edit `backend/app/core/pricing.py` to add new models or update pricing.

### Chat Statistics

Each chat session includes comprehensive analytics:

- **Token Breakdown**: Input, Output, Cached, Total
- **Cost Analysis**: Input cost, Output cost, Cached cost, Total cost
- **Agent Usage**: Which agents responded to messages
- **Tool Usage**: Which tools were called during conversations
- **Activity Timeline**: Detailed execution timeline from Langfuse
- **Session Metadata**: Model used, creation date, last update

---

## 🔌 API Reference

### Authentication

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/auth/signup/` | POST | User registration |
| `/api/auth/login/` | POST | User login (returns JWT tokens) |
| `/api/auth/refresh/` | POST | Refresh access token |
| `/api/auth/logout/` | POST | User logout |
| `/api/auth/change-password/` | POST | Change password |

### Users

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/users/me/` | GET | Get current user profile |
| `/api/users/me/update/` | PUT | Update user profile |
| `/api/users/me/stats/` | GET | Get user token usage statistics |

### Chat Sessions

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/chats/` | GET | List user's chat sessions |
| `/api/chats/` | POST | Create new chat session |
| `/api/chats/<id>/` | GET | Get chat session details |
| `/api/chats/<id>/` | DELETE | Delete chat session |
| `/api/chats/<id>/messages/` | GET | Get messages in session |
| `/api/chats/<id>/messages/` | POST | Send message (non-streaming) |
| `/api/chats/<id>/stats/` | GET | Get session statistics |

### Agent

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/agent/run/` | POST | Run agent (non-streaming) |
| `/api/agent/stream/` | POST | Stream agent response (SSE) |

**Example: Streaming Request**
```bash
curl -X POST http://localhost:8000/api/agent/stream/ \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "chat_session_id": 1,
    "message": "Hello, how are you?"
  }'
```

**Streaming Response Events** (SSE format):
```
event: token
data: {"type": "token", "data": "Hello"}

event: update
data: {"type": "update", "data": {"status": "Loading conversation history...", "task": "load_messages_task"}}

event: update
data: {"type": "update", "data": {"status": "Routing to agent...", "task": "supervisor_task"}}

event: update
data: {"type": "update", "data": {"status": "Processing with greeter agent...", "task": "greeter_agent_task"}}

event: token
data: {"type": "token", "data": "! "}

event: update
data: {"type": "update", "data": {"agent_name": "greeter", "tool_calls": []}}

event: done
data: {"type": "done"}
```

**Non-Streaming Response** (Pydantic `AgentResponse`):
```json
{
  "type": "answer",
  "reply": "Hello! Welcome! 😊 How can I assist you today?",
  "agent_name": "greeter",
  "tool_calls": [],
  "token_usage": {
    "input_tokens": 150,
    "output_tokens": 25,
    "total_tokens": 175
  }
}
```

**Response with Tool Calls**:
```json
{
  "type": "answer",
  "reply": "Here is the information retrieved regarding 'Madde 10'...",
  "agent_name": "search",
  "tool_calls": [
    {
      "id": "call_abc123",
      "name": "rag_retrieval_tool",
      "tool": "rag_retrieval_tool",
      "args": {"query": "Madde 10"},
      "status": "completed",
      "output": "MADDE 10 - Geri alma açıklaması..."
    }
  ],
  "token_usage": {
    "input_tokens": 500,
    "output_tokens": 300,
    "total_tokens": 800
  }
}
```

### Documents

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/documents/` | GET | List user's documents |
| `/api/documents/` | POST | Upload document |
| `/api/documents/<id>/` | DELETE | Delete document |

### Health

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health/` | GET | Health check |

---

## 🌟 Real-World Example

Let's walk through a complete example of how the system handles a user query:

### User Query: "What is Madde 10 according to docs?"

**Step 1: Request Received**
- User sends message via frontend
- Backend receives request: `AgentRequest(query="What is Madde 10 according to docs?", session_id=123)`

**Step 2: Workflow Execution** (`ai_agent_workflow`)

**Task 1: `load_messages_task`**
- Loads conversation history from PostgreSQL checkpoint
- Returns: `List[BaseMessage]` with previous messages
- **Status Update**: "Loading conversation history..." → "Loaded conversation history"

**Task 2: `supervisor_task`**
- Analyzes query intent using LLM
- Determines this is a document search question
- Returns: `RoutingDecision(agent="search", query="What is Madde 10 according to docs?")`
- **Status Update**: "Routing to agent..." → "Routed to agent"

**Task 3: `search_agent_task`**
- Search agent processes query
- Identifies need for RAG tool to search documents
- Proposes tool call: `rag_retrieval_tool(query="Madde 10")`
- **Status Update**: "Searching documents..." → (continues)

**Task 4: `tool_execution_task`**
- Executes `rag_retrieval_tool` with query="Madde 10"
- Performs vector search in PostgreSQL (pgvector)
- Retrieves relevant document chunks
- Returns: `ToolResult(tool="rag_retrieval_tool", output="MADDE 10 - Geri alma açıklaması...")`
- **Status Update**: "Executing tools..." → "Executed tools"
- **Tool Status**: "Executing rag_retrieval_tool..." → "Executed rag_retrieval_tool"

**Task 5: `agent_with_tool_results_task`**
- Search agent receives tool results
- Generates final response incorporating retrieved information
- Returns: `AgentResponse(reply="Here is the information...", tool_calls=[...])`
- **Status Update**: "Processing tool results..." → "Processed tool results"

**Task 6: `save_message_task`**
- Persists response to database with metadata
- Includes tool_calls, agent_name, token_usage
- **Status Update**: "Saving message..." → "Saved message"

**Step 3: Streaming to Frontend**

Throughout execution, events are streamed via SSE:

```
event: update
data: {"type": "update", "data": {"status": "Loading conversation history...", "task": "load_messages_task"}}

event: update
data: {"type": "update", "data": {"status": "Routing to agent...", "task": "supervisor_task"}}

event: update
data: {"type": "update", "data": {"status": "Searching documents...", "task": "search_agent_task"}}

event: update
data: {"type": "update", "data": {"status": "Executing rag_retrieval_tool...", "tool": "rag_retrieval_tool"}}

event: token
data: {"type": "token", "data": "Here"}

event: token
data: {"type": "token", "data": " is"}

... (more tokens) ...

event: update
data: {"type": "update", "data": {"agent_name": "search", "tool_calls": [{"name": "rag_retrieval_tool", "status": "completed", ...}]}}

event: done
data: {"type": "done"}
```

**Step 4: Observability**

In Langfuse UI (http://localhost:3001), you can see:
- Complete trace hierarchy
- Each task execution time
- Token usage per operation
- Tool execution details
- Cost breakdown
- Activity timeline

**Result**: User sees the answer with tool execution details, all in real-time with status updates throughout the process.

---

## ⚙️ Configuration

### Environment Variables

See `.env.example` for all configuration options:

**Required:**
- `OPENAI_API_KEY`: Your OpenAI API key
- `OPENAI_MODEL`: Model to use (default: `gpt-4o-mini`)

**Optional:**
- `LANGFUSE_ENABLED`: Enable Langfuse tracing (default: `false`)
- `LANGFUSE_PUBLIC_KEY`: Langfuse public key
- `LANGFUSE_SECRET_KEY`: Langfuse secret key
- `LANGFUSE_BASE_URL`: Langfuse server URL (default: `http://localhost:3001`)

**Database:**
- `DB_NAME`: Database name (default: `ai_agents_db`)
- `DB_USER`: Database user (default: `postgres`)
- `DB_PASSWORD`: Database password (default: `postgres`)

**Django:**
- `SECRET_KEY`: Django secret key (auto-generated if not set)
- `DEBUG`: Debug mode (default: `True` for development)

**PDF Extraction (RAG)**:
- `PDF_EXTRACTOR_PREFERENCE`: Preferred PDF extractor (`pdfplumber`, `pymupdf`, or `pypdf`). Default: `pdfplumber`
- `PDF_OCR_ENABLED`: Enable OCR for scanned PDFs (default: `True`)
- `PDF_OCR_MIN_TEXT_THRESHOLD`: Minimum characters per page to skip OCR (default: `50`)

**Chunking (RAG)**:
- `RAG_CHUNKING_STRATEGY`: Chunking strategy (`recursive` or `semantic`). Default: `recursive`
- `RAG_TOKEN_COUNTING_METHOD`: Token counting method (`tiktoken` or `estimation`). Default: `tiktoken`
- `RAG_TOKENIZER_MODEL`: Model name for tiktoken encoding (default: `gpt-4o-mini`)
- `RAG_CHUNK_SIZE`: Target chunk size in tokens (default: `1000`)
- `RAG_CHUNK_OVERLAP`: Overlap between chunks in tokens (default: `150`)

### Model Configuration

Edit `backend/app/core/pricing.py` to configure model pricing:

```python
MODEL_PRICING = {
    "gpt-4o-mini": {
        "input_price_per_1k": 0.15,   # $0.15 per 1K input tokens
        "output_price_per_1k": 0.60,  # $0.60 per 1K output tokens
    },
    # Add more models...
}
```

---

## ⚡ Performance & Scalability

### Streaming Performance

- **Token Latency**: First token appears within 100-500ms (depending on LLM response time)
- **Status Updates**: Real-time status updates with minimal overhead (<10ms per update)
- **SSE Efficiency**: Server-Sent Events provide efficient one-way streaming from server to client
- **Concurrent Streams**: System handles multiple concurrent streaming requests efficiently

### Database Checkpoint Efficiency

- **PostgreSQL Backend**: Uses `PostgresSaver` for persistent state management
- **Connection Resilience**: Automatic reconnection if database connection drops
- **Checkpoint Frequency**: State is checkpointed between major tasks, not every operation
- **Thread Isolation**: Each session has isolated checkpoint state via thread_id

### Concurrent Request Handling

- **Django ASGI**: Uses ASGI for async request handling
- **Background Threading**: Streaming runs in background threads to avoid blocking
- **Database Connection Pooling**: Efficient connection management for concurrent requests
- **State Isolation**: Each request has isolated state, preventing cross-contamination

### Resource Usage

- **Memory**: Efficient message handling with streaming (doesn't load full history into memory)
- **Database**: Indexed queries for fast message retrieval
- **Vector Search**: pgvector provides efficient semantic search with proper indexing
- **Token Counting**: tiktoken provides fast, accurate token counting

### Optimization Strategies

- **Checkpoint Caching**: Checkpoint state is cached to reduce database queries
- **Lazy Loading**: Messages loaded on-demand, not all at once
- **Streaming Optimization**: Tokens are batched for efficient SSE delivery
- **Tool Result Caching**: Tool results can be cached for repeated queries (future enhancement)

### Scalability Considerations

- **Horizontal Scaling**: Stateless API design allows horizontal scaling
- **Database Scaling**: PostgreSQL can be scaled with read replicas
- **Vector Search Scaling**: pgvector supports large document collections with proper indexing
- **Observability Scaling**: Langfuse can handle high-volume tracing

---

## 🧪 Testing

```bash
# Run all tests
docker-compose exec backend python manage.py test

# Run specific test file
docker-compose exec backend python manage.py test tests.test_auth

# Run with coverage (if configured)
docker-compose exec backend coverage run --source='.' manage.py test
docker-compose exec backend coverage report
```

---

## 📚 Documentation

### Project Documentation
- [Langfuse Integration Guide](./docs/LANGFUSE_INTEGRATION_GUIDE.md) - Comprehensive guide to Langfuse setup and usage
- [LangGraph Functional API Lessons Learned](./docs/LANGGRAPH_FUNCTIONAL_API_LESSONS_LEARNED.md) - Deep technical dive into Functional API implementation, patterns, pitfalls, and best practices

### External Documentation
- [Django Documentation](https://docs.djangoproject.com/)
- [LangChain Documentation](https://python.langchain.com/)
- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [Langfuse Documentation](https://python.reference.langfuse.com/langfuse)
- [pgvector Documentation](https://github.com/pgvector/pgvector)
- [React Documentation](https://react.dev/)
- [Vite Documentation](https://vitejs.dev/)

---

## 🗺️ Roadmap & Vision

Agent Playground is designed to be a comprehensive platform for AI agent development. Current focus areas:

### ✅ Implemented
- **LangGraph Functional API**: Complete implementation with `@entrypoint` and `@task` decorators
- **Multi-agent system**: Supervisor pattern with task-based architecture
- **Full observability**: Langfuse v3 integration with complete tracing
- **Token and cost tracking**: Real-time tracking with granular breakdowns
- **RAG infrastructure**: Complete RAG system with enhanced PDF extraction
  - Multiple PDF extraction backends with automatic fallback
  - OCR support for scanned PDFs
  - Semantic chunking with sentence boundary preservation
  - Accurate token counting with tiktoken
- **RAG Tool Integration**: ✅ **COMPLETE** - `rag_retrieval_tool` fully implemented and working
- **Search Agent**: ✅ **COMPLETE** - RAG-powered search agent that uses documents
- **Real-time Streaming**: Token streaming with live status updates
- **Type-Safe Architecture**: Pydantic models throughout
- **Multi-tenant architecture**: Complete user isolation
- **Production-ready API and frontend**: Battle-tested and deployed

### 🚧 In Progress / Planned
- **Database Tool**: Safe SQL query tool for agents
- **Web Search Tool**: External search API integration
- **Additional Agents**: Specialized agents for specific use cases (Gmail, Config, Process)
- **Advanced Analytics**: Enhanced metrics and reporting
- **API Documentation**: OpenAPI/Swagger documentation
- **Deployment Guides**: Production deployment best practices
- **Performance Optimization**: Further streaming and checkpoint optimizations

### 💡 Future Enhancements
- **Agent Marketplace**: Share and discover agents
- **Workflow Builder**: Visual agent workflow designer
- **Multi-model Support**: Support for Anthropic, Google, and other providers
- **Advanced RAG**: Hybrid search, enhanced re-ranking, and query optimization
- **Agent Fine-tuning**: Custom model fine-tuning capabilities
- **Collaboration Features**: Team workspaces and sharing
- **Additional Document Formats**: Support for Word, Excel, PowerPoint, and more

---

## 🤝 Contributing

Contributions are welcome! This is an active project with ongoing development.

**Areas for Contribution:**
- New agent implementations
- Tool development (RAG, DB, Web search)
- Frontend improvements
- Documentation enhancements
- Test coverage
- Performance optimizations

---

## 📄 License

MIT License - see LICENSE file for details.

---

## 🙏 Acknowledgments

Built with:
- [LangChain](https://github.com/langchain-ai/langchain) - LLM application framework
- [LangGraph](https://github.com/langchain-ai/langgraph) - Multi-agent orchestration
- [Langfuse](https://github.com/langfuse/langfuse) - AI observability platform
- [Django](https://www.djangoproject.com/) - Web framework
- [React](https://react.dev/) - UI library
- [pgvector](https://github.com/pgvector/pgvector) - Vector similarity search

---

**Ready to build the future of AI agents?** 🚀

Start by cloning the repository and following the [Quick Start](#-quick-start) guide above.
