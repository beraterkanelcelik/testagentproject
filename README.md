# 🤖 Agent Playground

> **A comprehensive, production-ready platform for building, testing, and deploying multi-agent AI systems with full observability, RAG capabilities, and enterprise-grade features.**

> **Note**: Development continues on dev privately.

Agent Playground is a full-stack monorepo that provides everything you need to build sophisticated AI agent applications. Built on industry-leading technologies (LangChain, LangGraph, Langfuse), it offers a complete solution from development to production with real-time observability, cost tracking, and multi-agent orchestration.

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

## ✨ Key Features

### 🧠 Multi-Agent System (LangGraph)
- **Supervisor Pattern**: Intelligent routing to specialized agents
- **Extensible Architecture**: Easy to add new agents (Greeter, RAG Agent, Custom Agents)
- **State Management**: Persistent conversation state with PostgreSQL checkpoints
- **Tool Framework**: Dynamic tool registration and discovery system
- **Streaming Support**: Real-time token streaming with SSE

### 📊 Full Observability (Langfuse v3)
- **Complete Tracing**: Track every LLM call, tool invocation, and agent decision
- **Token Analytics**: Real-time tracking of input, output, and cached tokens
- **Cost Monitoring**: Automatic cost calculation per model and session
- **Activity Timeline**: Visualize agent execution flows and tool usage
- **Self-Hosted or Cloud**: Deploy Langfuse locally or use cloud service

### 🔍 RAG (Retrieval-Augmented Generation)
- **Vector Search**: PostgreSQL with pgvector for semantic search
- **Document Ingestion**: Upload and process documents with automatic chunking
- **Multi-tenant Isolation**: Secure, user-scoped document access
- **Embedding Support**: Ready for OpenAI and other embedding models

### 💰 Cost & Token Tracking
- **Real-time Tracking**: Monitor tokens during streaming responses
- **Granular Breakdown**: Input, output, cached, and total tokens
- **Model-based Pricing**: Configurable pricing per model
- **Session Analytics**: Per-session and per-user statistics
- **Cost Attribution**: Track costs by agent, tool, and user

### 🔐 Production-Ready Features
- **Multi-user Authentication**: JWT-based auth with refresh tokens
- **Multi-tenant Architecture**: Complete user isolation at database level
- **RESTful API**: Comprehensive API with proper error handling
- **Hot Reload**: Development mode with automatic code reloading
- **Docker Compose**: One-command deployment for all services

### 🎨 Modern Frontend
- **React 18 + Vite**: Lightning-fast development experience
- **Tailwind CSS + shadcn/ui**: Beautiful, accessible UI components
- **Real-time Chat**: Streaming interface with agent identification
- **Statistics Dashboard**: Comprehensive analytics and insights
- **State Management**: Zustand with persistence

---

## 🏗️ Technology Stack

### Backend
- **Django 5.0+**: Robust web framework with REST API
- **LangChain**: Core LLM orchestration and tool integration
- **LangGraph**: Multi-agent state machine and routing
- **Langfuse v3**: AI observability and tracing (OpenTelemetry-based)
- **PostgreSQL + pgvector**: Vector database for RAG
- **Django REST Framework**: RESTful API with JWT authentication
- **PDF Processing**: pdfplumber, PyMuPDF, pypdf for document extraction
- **OCR**: pytesseract + pdf2image for scanned PDF support
- **Token Counting**: tiktoken for accurate token estimation
- **NLP**: spaCy (optional) for semantic chunking

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
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘  │
└──────────────────────┬──────────────────────────────────────┘
                       │ HTTP/SSE
┌──────────────────────┴──────────────────────────────────────┐
│              Django REST API (Backend)                       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │   Auth API   │  │   Chat API   │  │  Agent API   │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │         LangGraph Multi-Agent System                  │  │
│  │  ┌────────────┐      ┌────────────┐                  │  │
│  │  │ Supervisor │ ────▶│   Agent    │                  │  │
│  │  └────────────┘      └────────────┘                  │  │
│  │         │                   │                         │  │
│  │         ▼                   ▼                         │  │
│  │  ┌────────────┐      ┌────────────┐                  │  │
│  │  │  Greeter   │      │   Tools    │                  │  │
│  │  └────────────┘      └────────────┘                  │  │
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
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘    │
└─────────────────────────────────────────────────────────────┘
```

### Backend Architecture

#### Agent System (`app/agents/`)
```
agents/
├── agents/              # Agent implementations
│   ├── base.py         # BaseAgent abstract class
│   ├── supervisor.py   # Routing agent
│   └── greeter.py      # Welcome agent
├── graphs/              # LangGraph definitions
│   ├── graph.py        # Main graph definition
│   ├── nodes.py        # Graph nodes (supervisor, agent, tool)
│   ├── routers.py      # Conditional routing logic
│   └── state.py        # AgentState TypedDict
├── tools/               # Agent tools
│   ├── base.py         # BaseTool interface
│   ├── registry.py     # Tool registration system
│   ├── rag_tool.py     # RAG retrieval (TODO)
│   ├── db_tool.py      # Database queries (TODO)
│   └── web_tool.py      # Web search (TODO)
├── checkpoint.py        # PostgreSQL checkpoint adapter
├── config.py            # Agent configuration
└── runner.py            # Graph execution & streaming
```

**Key Components:**
- **StateGraph**: LangGraph state machine with supervisor pattern
- **Checkpoint Persistence**: PostgreSQL-backed conversation state
- **Tool System**: Extensible tool registry with LangChain integration
- **Streaming**: Real-time token streaming with SSE

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
│   ├── chat/           # Chat interface
│   ├── auth/           # Authentication
│   └── DashboardPage   # Main dashboard
├── components/          # Reusable components
│   └── ui/             # shadcn/ui components
├── state/               # Zustand stores
│   ├── useAuthStore    # Authentication state
│   └── useChatStore    # Chat state
└── lib/                 # Utilities
    ├── api.ts          # API client
    └── streaming.ts    # SSE streaming
```

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

### Adding a New Agent

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

2. **Register in supervisor** (`backend/app/agents/agents/supervisor.py`):
   ```python
   from app.agents.agents.my_agent import MyAgent
   
   # Add to available_agents list
   ```

3. **Update router** (`backend/app/agents/graphs/routers.py`):
   ```python
   # Add routing logic for your agent
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
   ```

---

## 📊 Features in Detail

### Multi-Agent System

**Supervisor Pattern**: The supervisor agent intelligently routes user messages to specialized agents based on context and intent.

**Current Agents:**
- **Supervisor**: Routes messages to appropriate agents
- **Greeter**: Handles initial interactions and provides guidance

**Extensibility**: Adding new agents is straightforward - inherit from `BaseAgent`, define system prompts and tools, and register with the supervisor.

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
- Multi-agent system with supervisor pattern
- Full observability with Langfuse
- Token and cost tracking
- RAG infrastructure with enhanced PDF extraction
  - Multiple PDF extraction backends with automatic fallback
  - OCR support for scanned PDFs
  - Semantic chunking with sentence boundary preservation
  - Accurate token counting with tiktoken
- Multi-tenant architecture
- Production-ready API and frontend

### 🚧 In Progress / Planned
- **RAG Tool Integration**: Complete RAG tool for agents to retrieve context
- **Database Tool**: Safe SQL query tool for agents
- **Web Search Tool**: External search API integration
- **Additional Agents**: Specialized agents for specific use cases
- **Advanced Analytics**: Enhanced metrics and reporting
- **API Documentation**: OpenAPI/Swagger documentation
- **Deployment Guides**: Production deployment best practices

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
