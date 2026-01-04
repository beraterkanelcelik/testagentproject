# AI Agent Test Website

A monorepo project for building and testing AI agents using Django, LangChain, LangGraph, PostgreSQL with pgvector, and React + Vite frontend.

## Project Structure

```
TestAgentProject/
├─ README.md
├─ .gitignore
├─ .env.example
├─ docker-compose.yml          # Root level orchestration
├─ Makefile                    # Convenience commands
├─ scripts/                    # Utility scripts
│  ├─ dev.sh
│  └─ seed_demo_data.py
│
├─ infra/                      # Infrastructure configs
│  ├─ postgres/
│  │  ├─ init.sql
│  │  └─ extensions.sql       # pgvector extension
│  └─ nginx/
│     └─ nginx.conf
│
├─ backend/                    # Django backend
│  ├─ Dockerfile
│  ├─ requirements.txt
│  ├─ manage.py
│  ├─ .env.example
│  ├─ tests/
│  └─ app/                     # Main Django app
│     ├─ settings.py
│     ├─ urls.py
│     ├─ api/                   # API endpoints
│     ├─ core/                  # Core utilities
│     ├─ db/                    # Database models
│     ├─ services/              # Business logic
│     ├─ rag/                   # RAG components
│     ├─ agents/                # LangGraph agents
│     └─ observability/         # Tracing
│
└─ frontend/                   # React + Vite frontend
   ├─ Dockerfile
   ├─ package.json
   ├─ vite.config.ts
   ├─ tailwind.config.js
   ├─ .env.example
   └─ src/
      ├─ app/
      ├─ components/
      ├─ lib/
      └─ state/
```

## Prerequisites

- Docker and Docker Compose
- Git (optional)

## Quick Start

1. **Create environment file:**
   ```bash
   copy .env.example .env
   # On macOS/Linux: cp .env.example .env
   ```

2. **Edit `.env` file** with your API keys and configuration

3. **Start all services:**
   ```bash
   make up
   # Or: docker-compose up -d
   ```

4. **Run migrations:**
   ```bash
   make migrate
   ```

5. **Access the application:**
   - Frontend: http://localhost:3000
   - Backend API: http://localhost:8000
   - Nginx Proxy: http://localhost
   - Admin: http://localhost/admin/

## Makefile Commands

```bash
make help          # Show all available commands
make build         # Build all Docker images
make up            # Start all services
make down          # Stop all services
make restart       # Restart all services
make logs          # Show logs from all services
make migrate       # Run database migrations
make superuser     # Create Django superuser
make test          # Run tests
make clean         # Remove all containers and volumes
```

## Development

### Backend Development

```bash
# Open backend shell
make shell-backend

# Create migrations
make makemigrations

# Run migrations
make migrate

# Run tests
make test
```

### Frontend Development

The frontend runs in development mode with hot-reload enabled. Changes are automatically reflected.

### Database Access

```bash
# Open psql shell
make shell-db

# Or directly
docker-compose exec db psql -U postgres -d ai_agents_db
```

## Key Features Details

### Chat Statistics
Each chat session includes a comprehensive stats tab showing:
- **Token Breakdown**: Input, Output, Cached, and Total tokens
- **Cost Calculation**: Automatic price calculation based on model pricing
  - Input cost
  - Output cost
  - Cached cost
  - Total cost
- **Agent Usage**: Which agents responded to messages
- **Tool Usage**: Which tools were called during the conversation
- **Session Info**: Model used, creation date, last update

### Agent System
- **Supervisor Agent**: Routes messages to appropriate sub-agents
- **Greeter Agent**: Handles initial interactions and guidance
- **Extensible Architecture**: Easy to add new agents (e.g., Gmail agent)
- **Tool Framework**: Dynamic tool registration and discovery
- **Checkpoint System**: Conversation state persistence using PostgreSQL

### Token Tracking
- Real-time token usage tracking during streaming
- Separate tracking for input, output, and cached tokens
- Automatic cost calculation based on model pricing
- Per-message, per-session, and per-user token statistics

### Pricing System
- Configurable pricing per model in `backend/app/core/pricing.py`
- Supports multiple models with different pricing tiers
- Automatic cost calculation based on token usage
- Easy to extend for new models

## Architecture

### Backend (Django)

- **API Layer** (`app/api/`): REST API endpoints
- **Core** (`app/core/`): Configuration, security, logging, pricing
- **Database** (`app/db/`): Models and database operations
- **Services** (`app/services/`): Business logic (chat, user, document services)
- **Account** (`app/account/`): User model, authentication, profile management
- **RAG** (`app/rag/`): Document processing and vector search
- **Agents** (`app/agents/`): LangGraph agent definitions
  - Base agent framework
  - Supervisor agent (routing)
  - Greeter agent (initial interactions)
  - Tool registry system
  - Graph nodes and state management
  - Checkpoint persistence
- **Observability** (`app/observability/`): LangSmith tracing

### Frontend (React + Vite)

- **Framework**: React 18 with Vite
- **UI**: Tailwind CSS + shadcn/ui components
- **State Management**: Zustand with persistence
- **Routing**: React Router v6
- **API Client**: Axios with JWT interceptors
- **Streaming**: SSE (Server-Sent Events) for real-time agent responses
- **Features**:
  - Chat interface with agent name display
  - Stats tab showing token usage, costs, and agent/tool statistics
  - User profile management
  - Token usage tracking per chat and globally

### Database (PostgreSQL + pgvector)

- Multi-tenant architecture with user isolation
- Vector embeddings for RAG
- All queries filtered by `user_id`

## Features

- ✅ Multi-user authentication (JWT)
- ✅ Chat sessions and messages with agent identification
- ✅ Real-time streaming chat interface
- ✅ Comprehensive chat statistics:
  - Token usage breakdown (Input, Output, Cached)
  - Cost calculation per model
  - Agent usage tracking
  - Tool usage tracking
  - Session information
- ✅ Document upload and ingestion
- ✅ RAG with pgvector
- ✅ LangGraph multi-agent architecture:
  - Supervisor agent for routing
  - Greeter agent for initial interactions
  - Extensible agent framework
- ✅ LangGraph checkpoint persistence (PostgreSQL)
- ✅ LangSmith tracing and observability
- ✅ Token usage tracking with pricing
- ✅ Model configuration system (easily switchable)
- ✅ Hot-reload for development

## API Endpoints

### Authentication
- `POST /api/auth/signup/` - User registration
- `POST /api/auth/login/` - User login
- `POST /api/auth/refresh/` - Refresh access token
- `POST /api/auth/logout/` - User logout
- `POST /api/auth/change-password/` - Change password

### Users
- `GET /api/users/me/` - Get current user profile
- `PUT /api/users/me/update/` - Update user profile
- `GET /api/users/me/stats/` - Get user token usage statistics

### Chat Sessions
- `GET /api/chats/` - List user's chat sessions
- `POST /api/chats/` - Create new chat session
- `GET /api/chats/<id>/` - Get chat session details
- `DELETE /api/chats/<id>/` - Delete chat session
- `GET /api/chats/<id>/messages/` - Get messages in session
- `POST /api/chats/<id>/messages/` - Send message (non-streaming)
- `GET /api/chats/<id>/stats/` - Get session statistics (tokens, costs, agent usage)

### Agent
- `POST /api/agent/run/` - Run agent (non-streaming)
- `POST /api/agent/stream/` - Stream agent response (SSE)

### Documents
- `GET /api/documents/` - List user's documents
- `POST /api/documents/` - Upload document
- `DELETE /api/documents/<id>/` - Delete document

### Health
- `GET /api/health/` - Health check

## Environment Variables

See `.env.example` for all required environment variables:

- Django configuration
- PostgreSQL connection
- LangSmith API keys
- OpenAI API keys

## Documentation

- [Django Documentation](https://docs.djangoproject.com/)
- [LangChain Documentation](https://python.langchain.com/)
- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [pgvector Documentation](https://github.com/pgvector/pgvector)
- [React Documentation](https://react.dev/)
- [Vite Documentation](https://vitejs.dev/)
- [Tailwind CSS Documentation](https://tailwindcss.com/)
- [shadcn/ui Documentation](https://ui.shadcn.com/)

## License

MIT
