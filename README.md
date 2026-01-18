# Agent Playground

> **Production-ready multi-agent platform built on LangGraph Functional API**  
> Real-time streaming, full observability, intelligent routing, and RAG — end to end.

<!-- ✅ Demo video (replace the path with your repo file path) -->
<video src="./assets/demo.mp4" controls muted playsinline style="max-width: 100%; border-radius: 12px;"></video>

---

## What is it?

Agent Playground is a full-stack platform for building and running **multi-agent AI systems in production** — not a demo framework.  
It ships with a real-time UI, durable workflows, cost/token tracking, and built-in observability.

---

## Highlights

- **LangGraph Functional API** workflow (`@entrypoint`, `@task`) with type-safe Pydantic models
- **Multi-agent orchestration** with supervisor-based routing to specialized agents
- **Real-time streaming UI** (SSE) with live task + tool status updates
- **Full observability** via **Langfuse** (LLM calls, tools, routing decisions, costs)
- **RAG built-in** using **Postgres + pgvector** (PDF/MD/TXT ingestion, chunking, retrieval tool)
- **Production foundations**: auth, multi-tenant isolation, persistence, Docker Compose

---

## Architecture (high level)

**React UI → Django API → Temporal workflows → LangGraph Functional tasks**  
Streaming path: **Redis pub/sub → SSE → UI**  
State & RAG: **PostgreSQL (checkpoints + pgvector)**  
Tracing: **Langfuse**

---

## Quick Start

### Prerequisites
- Docker + Docker Compose

### Run
```bash
cp .env.example .env
# set OPENAI_API_KEY in .env

docker-compose up -d
docker-compose exec backend python manage.py migrate
````

### Open

* Frontend: [http://localhost:3000](http://localhost:3000)
* Backend: [http://localhost:8000](http://localhost:8000)
* Langfuse: [http://localhost:3001](http://localhost:3001) (if enabled)

---

## Configuration

Required:

```env
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-4o-mini
```

Optional (Langfuse):

```env
LANGFUSE_ENABLED=true
LANGFUSE_PUBLIC_KEY=...
LANGFUSE_SECRET_KEY=...
LANGFUSE_BASE_URL=http://localhost:3001
```

---

## Repo guide

* `backend/` Django + agent runtime
* `frontend/` React streaming UI
* `docs/` deep dives (Functional API, Temporal+Redis streaming, Langfuse)

---

## License

MIT
