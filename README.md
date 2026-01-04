# AI Agents Project with LangChain and LangGraph

A clean, modular project structure for building and testing AI agents using LangChain, LangGraph, Streamlit, and LangSmith for tracing and observability.

## Project Structure

```
TestAgentProject/
├── .env.example              # Environment variables template
├── .gitignore               # Git ignore rules
├── .dockerignore            # Docker ignore rules
├── Dockerfile               # Docker image configuration
├── docker-compose.yml       # Docker Compose configuration
├── README.md                # Project documentation
├── requirements.txt         # Python dependencies
├── app.py                   # Main Streamlit chat interface
├── agents/                  # Agent implementations
│   ├── __init__.py
│   └── base_agent.py       # Base agent class skeleton
├── utils/                   # Utility modules
│   ├── __init__.py
│   ├── logger.py           # Generic logger (LangSmith integration ready)
│   └── config.py           # Configuration loader
└── config/                  # Configuration files
    ├── __init__.py
    └── settings.py         # Settings management
```

## Prerequisites

- Docker and Docker Compose installed on your system
- Git (optional, for version control)

## Setup Instructions

### 1. Initialize Git Repository (Optional)

```bash
git init
git add .
git commit -m "Initial commit: AI Agents project structure"
```

### 2. Environment Configuration

1. Create `.env` file from the example:
   ```bash
   # On Windows:
   copy .env.example .env
   # On macOS/Linux:
   cp .env.example .env
   ```

2. Edit `.env` file and add your LangSmith API key:
   - Get your API key from [https://smith.langchain.com/](https://smith.langchain.com/)
   - Replace `your_langsmith_api_key_here` with your actual API key
   - Ensure `LANGCHAIN_TRACING_V2=true` is set

### 3. Build and Run with Docker

```bash
# Build the Docker image
docker-compose build

# Start the application
docker-compose up

# Or run in detached mode (background)
docker-compose up -d
```

The application will be available at: **http://localhost:8501**

### 4. Docker Commands

```bash
# Stop the application
docker-compose down

# View logs
docker-compose logs -f

# Rebuild after code changes
docker-compose build --no-cache

# Execute commands in the container
docker-compose exec ai-agents-app bash

# Restart the container
docker-compose restart
```

## Features

- **Dockerized Environment**: Containerized setup for consistent development and deployment
- **Modular Architecture**: Clean separation of concerns with dedicated folders for agents, utilities, and configuration
- **LangSmith Integration**: Built-in support for tracing and observability
- **Streamlit Interface**: Ready-to-use chat interface for interacting with agents
- **Type Hints**: All skeleton code includes type hints for better code clarity
- **Well Documented**: Comprehensive docstrings and comments for study purposes
- **Hot Reload**: Code changes are automatically reflected in the running container

## Next Steps

This is a skeleton structure. You can now:
- Implement your agent logic in `agents/base_agent.py`
- Add new agents by extending the base agent class
- Configure logging and tracing in `utils/logger.py`
- Customize settings in `config/settings.py`

## Dependencies

- **LangChain**: Framework for building LLM applications
- **LangGraph**: For creating stateful, multi-actor applications
- **Streamlit**: For building the chat interface
- **LangSmith**: For tracing, debugging, and monitoring LLM applications
