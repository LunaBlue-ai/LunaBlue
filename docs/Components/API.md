# API + Main Local LLM Loop (FastAPI)

## Purpose

This component is the core service container for LunaBlue. It hosts the React frontend, exposes prompt and agent APIs, maintains shared runtime state, manages WebSocket updates, and executes LangGraph orchestration with an in-process `llama.cpp` LLM.

## Responsibilities

- serve the React frontend as static assets
- receive prompt submissions and agent status requests
- validate, normalize, and govern incoming prompts
- log incoming prompt requests and prompt responses to Postgres
- host the main LangGraph orchestrator and background agent runners
- maintain shared in-memory state for sessions and agents
- optionally push state updates to the UI via WebSockets
- reuse a single global LLM instance in-process

## Directory Mapping

This component lives under `backend/` in the repository layout defined in [Architecture.md](../Architecture.md#directory-structure). Each responsibility maps to a subpackage of `backend/app/`:

- `main.py` — app factory; the lifespan handler loads config, creates the SQLAlchemy engine, instantiates the global llama.cpp runtime once, initializes the state store, then mounts routes and static files.
- `config.py` — pydantic-settings: model path, DB URL, WebSocket options, governance flags, guard limits; `startup.py` validates them fail-fast at boot.
- `api/` — HTTP/WS surface, routing only: `routes/prompt.py` (POST `/api/prompt`), `routes/agents.py` (GET `/api/agents`, GET `/api/agents/{id}`, POST `/api/agents/{id}/cancel`), `routes/state.py` (GET `/api/runs/{request_id}`, GET `/api/sessions/{session_id}` — the polling fallback), `routes/health.py` (`/api/health`, `/api/health/ready`), `websocket.py` (`/ws`), `errors.py` (error taxonomy), and Pydantic `schemas/`.
- `governance/` — prompt intake: `intake.py` (normalization and enrichment), `policy.py` (policy tags, safety directives).
- `orchestration/` — `graph.py` (main request graph), `pipeline.py` (runs the graph for one prompt: state updates + audit events per phase), `nodes/` (prompt engineering, LLM review, agent spawn, respond), `agents/` (background subgraphs; `research.py` is the built-in agent), `runner.py` (background execution / task queue).
- `llm/` — `runtime.py` holds the single global `llama-cpp-python` instance; `prompts/` holds templates. No other package touches llama.cpp directly.
- `state/` — `store.py` (session, graph, and agent state + task queues), `events.py` (pub/sub bridge to WebSocket broadcasts).
- `audit/` — Postgres integration; see [AUDIT.md](AUDIT.md).
- `static/` — built frontend output, copied in at build time (gitignored).

## Build Approach

1. Build a FastAPI service that serves frontend static files and API routes from the same process.
2. Define Pydantic request/response models for prompt and agent endpoints under `api/schemas/`.
3. Add request logging, tracing, governance enforcement, and audit hooks.
4. Implement initial prompt intake in `governance/` that performs prompt engineering and applies safety metadata.
5. Instantiate a single global `llama.cpp` runtime with `llama-cpp-python` in `llm/runtime.py`, created once in the `main.py` lifespan handler.
6. Implement the main LangGraph pipeline and long-running agent subgraphs in `orchestration/`.
7. Maintain runtime state in memory in `state/store.py`; Postgres is the primary durable store, with local caches used only for performance.
8. Persist prompt request/response audit data and governance metadata to Postgres via `audit/service.py`.

## Implementation Notes

- Use FastAPI's async support and static file mounting for the frontend.
- Keep shared runtime state in-process and expose it through HTTP/WebSocket endpoints.
- Graph nodes mutate shared state only through `state/`; `state/events.py` is the only bridge to `api/websocket.py`, so orchestration code never knows about WebSockets.
- Prefer in-process model execution over external model servers.
- Separate API routing (`api/`) from orchestration (`orchestration/`) and state management (`state/`) logic.
- Expose health checks and a minimal frontend API surface for prompt/agent lifecycle.

## Hardening (Step 17)

- **Liveness vs. readiness:** `GET /api/health` proves the process is up and
  never touches dependencies; `GET /api/health/ready` reports per-dependency
  checks (`model`, `database`, `audit_queue`, `agent_runner`) and answers 503
  with the same body shape while any of them is degraded.
- **Error taxonomy (`api/errors.py`):** every non-2xx JSON response carries
  `{code, message, request_id, detail}`. Codes include `validation_error`,
  `governance_rejected`, `generation_timeout`, `generation_failed`, `busy`,
  `not_found`, `conflict`, `unavailable`, and `internal_error`. Responses
  never leak stack traces, exception text, or file paths — those go to the
  process log keyed by the `request_id` echoed in the `X-Request-ID` header.
- **Guards:** startup validation aborts boot with one aggregated, actionable
  message on any misconfiguration; every `LlamaRuntime.generate()` call has a
  configurable timeout; the busy guard 503s new prompts once the generation
  queue exceeds `LLM_MAX_QUEUE_DEPTH`; agents are bounded by
  `AGENT_TIMEOUT_SECONDS` and `AGENT_MAX_STEPS`; a llama.cpp crash marks the
  runtime unhealthy (reported by readiness) and self-heals on the next
  successful generation.
- **WebSocket resilience:** the server heartbeats `/ws` every
  `WS_HEARTBEAT_SECONDS` so dead connections are reaped, and an overflowed
  subscriber's next event carries `degraded: true` so the client resyncs
  from a fresh snapshot.

## Governance and Runtime Integration

The API service applies request governance as part of prompt intake. Governance responsibilities include:

- normalizing and enriching incoming prompt text
- tagging requests with policy metadata and safety directives
- logging the initial prompt and reviewed prompt to Postgres

The API service then invokes the local LLM and LangGraph orchestrator, which:

- performs initial prompt review and planning
- spawns or updates background agents if needed
- synthesizes final responses and updates shared state
- logs prompt responses and final outputs to Postgres
