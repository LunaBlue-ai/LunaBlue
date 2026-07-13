# LunaBlue Architecture

## Overview

LunaBlue is a Python-first, local AI assistant architecture built around FastAPI, React, LangGraph, and an in-process `llama.cpp` runtime. The backend is written in Python, the frontend is a React app, and Postgres is the primary durable database for auditing and state persistence.

## High-level architecture

- **Frontend:** React app served by FastAPI.
- **Backend:** Python FastAPI service hosting:
  - the frontend static app
  - API endpoints for prompt submission and agent status
  - the main LangGraph orchestrator
  - background agent execution
  - an in-process local LLM via `llama-cpp-python`
  - runtime state accessible by both API and frontend via WebSockets
- **State:** in-memory state with durable persistence in Postgres.
- **Audit:** prompt requests and prompt responses logged to Postgres.

## Architecture diagram

The service structure follows the diagram:

- `user` interacts with `Web React`
- `Web React` communicates with `API` over HTTP and optionally WebSockets
- `API` and `LangGraph / llama.cpp` run inside the same FastAPI process
- shared service `State` is managed in-memory and exposed for UI updates
- `Log / Audit` is persisted externally in Postgres

## Components

### 1. FastAPI service

The FastAPI service is the container for the whole system.

Responsibilities:

- serve React static assets
- host prompt and agent API endpoints
- maintain in-memory state for the active session and agents
- optionally expose WebSocket endpoints for live frontend updates
- persist prompt and response audit data to Postgres
- instantiate and reuse a single global LLM runtime

### 2. Web React frontend

The React UI is served by FastAPI and interacts with the backend through:

- HTTP APIs for prompt submission and agent status
- WebSockets for state updates and live progress streaming

### 3. Local LLM and LangGraph orchestration

The LLM and graph orchestration live inside the backend process.

Responsibilities:

- execute the main request graph
- run background agent subgraphs
- route prompt flow through prompt engineering, LLM review, agent spawn, and response generation
- share state with the API service for frontend visibility

### 4. Shared state

Service state is held in-process and may include:

- main graph state
- agent state and task queues
- active session metadata
- live status for frontend updates

Durable persistence is provided by Postgres for audit records and application state. Local caches may be used for performance, but Postgres is the primary database.

### 5. Postgres Log / Audit

Postgres stores audit records from the service, including:

- raw prompt requests
- reviewed prompt text
- prompt responses from the local LLM
- final outputs
- governance and decision metadata

## Directory structure

A clear separation of concerns is recommended. The layout below can be used to scaffold the solution repository; it maps each area to the component documents in [Components/](Components/).

```text
lunablue/
├── README.md
├── .gitignore
├── .env.example                    # documented environment variables (DB URL, model path, ports)
├── docker-compose.yml              # local Postgres (and optional pgAdmin) for development
│
├── backend/                        # Python FastAPI service (Components/API.md)
│   ├── pyproject.toml              # project metadata + deps (fastapi, langgraph, llama-cpp-python, sqlalchemy, alembic)
│   ├── alembic.ini
│   ├── migrations/                 # Alembic migrations for the audit/state schema
│   │   └── versions/
│   └── app/
│       ├── __init__.py
│       ├── main.py                 # app factory: lifespan startup, static mount, router registration
│       ├── config.py               # pydantic-settings: model path, DB URL, WS options, governance flags
│       │
│       ├── api/                    # HTTP/WS surface — routing only, no business logic
│       │   ├── __init__.py
│       │   ├── routes/
│       │   │   ├── __init__.py
│       │   │   ├── prompt.py       # POST /api/prompt — prompt submission
│       │   │   ├── agents.py       # GET /api/agents, /api/agents/{id} — agent status
│       │   │   └── health.py       # health/readiness checks
│       │   ├── websocket.py        # WS endpoint pushing shared-state and agent lifecycle updates
│       │   └── schemas/            # Pydantic request/response models
│       │       ├── __init__.py
│       │       ├── prompt.py
│       │       └── agent.py
│       │
│       ├── governance/             # prompt intake governance (Components/API.md — Governance section)
│       │   ├── __init__.py
│       │   ├── intake.py           # normalization and enrichment of incoming prompt text
│       │   └── policy.py           # policy tags, safety directives, governance metadata
│       │
│       ├── orchestration/          # LangGraph graphs and background agents
│       │   ├── __init__.py
│       │   ├── graph.py            # main request graph definition
│       │   ├── nodes/              # individual graph nodes
│       │   │   ├── __init__.py
│       │   │   ├── prompt_engineering.py
│       │   │   ├── llm_review.py
│       │   │   ├── agent_spawn.py
│       │   │   └── respond.py      # final response synthesis
│       │   ├── agents/             # background agent subgraphs
│       │   │   ├── __init__.py
│       │   │   └── base.py         # shared agent lifecycle contract
│       │   └── runner.py           # background execution / task queue for agent subgraphs
│       │
│       ├── llm/                    # in-process llama.cpp runtime
│       │   ├── __init__.py
│       │   ├── runtime.py          # single global llama-cpp-python instance (created at startup)
│       │   └── prompts/            # prompt templates used by graph nodes
│       │
│       ├── state/                  # shared in-memory runtime state
│       │   ├── __init__.py
│       │   ├── store.py            # session, graph, and agent state + task queues
│       │   └── events.py           # pub/sub bridge from state changes to WebSocket broadcasts
│       │
│       ├── audit/                  # Postgres log/audit (Components/AUDIT.md)
│       │   ├── __init__.py
│       │   ├── db.py               # SQLAlchemy engine and session management
│       │   ├── models.py           # tables: prompt_requests, prompt_responses, agent_events, sessions
│       │   └── service.py          # structured audit writer, decoupled from the request path
│       │
│       └── static/                 # built frontend output copied here at build time (gitignored)
│
├── frontend/                       # React app (Components/WEB.md)
│   ├── package.json
│   ├── vite.config.ts              # build output wired to backend/app/static (or copied by script)
│   ├── index.html
│   ├── tsconfig.json
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── api/
│       │   ├── client.ts           # HTTP client for /api/prompt and agent status
│       │   └── ws.ts               # WebSocket connection with polling fallback
│       ├── components/
│       │   ├── Chat/               # prompt input and response display
│       │   ├── AgentPanel/         # agent IDs, queue status, last results
│       │   └── StatusBar/          # backend connectivity and session status
│       ├── hooks/                  # useWebSocket, usePromptSubmit, useAgentStatus
│       ├── state/                  # React context for prompts, agents, live progress
│       └── types/                  # shared TS types mirroring backend schemas
│
├── models/                         # local GGUF model files (gitignored; README explains how to fetch)
│   └── README.md
│
├── docs/                           # this documentation set
│   ├── Architecture.md
│   └── Components/
│       ├── API.md
│       ├── AUDIT.md
│       └── WEB.md
│
├── tests/
│   ├── backend/                    # pytest suites
│   │   ├── conftest.py             # app fixture, test DB, fake LLM runtime
│   │   ├── test_api/               # route-level tests (prompt, agents, health, WS)
│   │   ├── test_governance/
│   │   ├── test_orchestration/     # graph and node tests with the LLM stubbed
│   │   └── test_audit/
│   └── frontend/                   # Vitest/RTL suites (or colocate in frontend/src if preferred)
│
└── scripts/
    ├── setup.ps1 / setup.sh        # create venv, install deps, install frontend packages
    ├── build_frontend.ps1          # build React app and copy dist into backend/app/static
    ├── migrate.ps1                 # run Alembic migrations against Postgres
    └── download_model.ps1          # fetch the GGUF model into /models
```

### Directory design rationale

**One process, separated concerns.** Everything under `backend/app/` runs in the single FastAPI process, per the design principles below. The subpackages enforce the separation called out in [Components/API.md](Components/API.md): `api/` does routing only, `governance/` owns prompt intake policy, `orchestration/` owns LangGraph, `llm/` owns the model runtime, `state/` owns shared memory, and `audit/` owns Postgres writes. Nothing outside `llm/` touches llama.cpp directly, which keeps the "single global LLM instance" rule enforceable.

**Startup order lives in `main.py`.** The FastAPI lifespan handler is the natural place to: load config, create the SQLAlchemy engine, instantiate the global llama.cpp runtime once, initialize the state store, then mount routes and static files. Shutdown reverses this.

**State → WebSocket flow.** `state/store.py` holds the in-memory truth; `state/events.py` is the only bridge to `api/websocket.py`. This keeps orchestration code from knowing anything about WebSockets — graph nodes just mutate state, and subscribers broadcast.

**Frontend build integration.** The React app is developed standalone with the Vite dev server (proxying `/api` and `/ws` to FastAPI), and for deployment `scripts/build_frontend` copies the production bundle into `backend/app/static`, which FastAPI mounts. The `static/` directory is gitignored — it is a build artifact.

**Audit decoupling.** `audit/service.py` should accept structured events and write them off the hot path (background task or queue), per the implementation note in [Components/AUDIT.md](Components/AUDIT.md). Alembic migrations live with the backend since the schema is owned by the Python service.

**Tests at the root.** Backend tests stub the LLM runtime via `conftest.py` fixtures so the suite runs without a model file. If the team prefers colocated frontend tests (`frontend/src/__tests__`), that is a reasonable deviation — the root `tests/frontend` folder is only needed if CI wants one test root.

**Models are data, not code.** `/models` holds GGUF artifacts and is gitignored; `scripts/download_model` plus a README make the setup reproducible without committing multi-gigabyte files.

## Updated workflow

1. The user opens the React UI served by FastAPI.
2. The UI submits a prompt to the backend.
3. FastAPI ingests the prompt, logs it, and updates state.
4. The main LangGraph orchestrator runs inside the same FastAPI process.
5. Prompt engineering, LLM review, and any agent spawning occur in-process.
6. Shared state is kept live and can be pushed to the frontend via WebSockets.
7. Prompt responses and final output are persisted to Postgres.
8. The frontend receives the result and agent status updates.

## Design principles

- keep the system local and self-contained inside FastAPI
- serve the React UI and execute orchestration from the same service
- use WebSockets for live state updates rather than polling only
- retain prompt and response audit trails in Postgres
- prefer in-process LLM execution with `llama-cpp-python` over remote model servers

## Notes

- The FastAPI service is both the frontend server and the backend runtime.
- The local `llama.cpp` instance is shared by all graph execution paths.
- WebSockets are recommended for real-time UI state and agent lifecycle updates.
- Postgres remains the external store for audit logs, while runtime state is primarily in-memory.

