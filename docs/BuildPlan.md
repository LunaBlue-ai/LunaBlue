# LunaBlue Build Plan

This plan breaks the solution defined in [Architecture.md](Architecture.md) into incremental steps. Each step produces something runnable and verifiable, so progress is observable at every stage. Each step has a corresponding detailed execution prompt in [Steps/](Steps/README.md), ready to be given to an LLM coding agent. Steps 1–8 build a minimal end-to-end prompt loop; steps 9–15 layer in orchestration, the frontend, and agents; steps 16–18 finish testing, hardening, and release.

## Phase 1 — Foundation and the first prompt loop

**Step 1. Scaffold the repository.**
Create the solution repo using the directory structure in [Architecture.md](Architecture.md#directory-structure): `backend/`, `frontend/`, `models/`, `docs/`, `tests/`, `scripts/`, plus `.gitignore`, `.env.example`, and `docker-compose.yml`. Copy this documentation set into `docs/`.

**Step 2. Stand up the backend skeleton.**
Build the FastAPI app factory (`main.py`), settings via pydantic-settings (`config.py`), and a health endpoint. *Checkpoint: the service starts and `/api/health` responds.*

**Step 3. Provision Postgres and the schema.**
Add Postgres to `docker-compose.yml`, create the SQLAlchemy engine and session management (`audit/db.py`), initialize Alembic, and write the first migration for `prompt_requests`, `prompt_responses`, `agent_events`, and `sessions`. *Checkpoint: `scripts/migrate` creates the schema in a local Postgres.*

**Step 4. Build the audit service.**
Implement the SQLAlchemy models (`audit/models.py`) and the structured audit writer (`audit/service.py`), writing off the hot path. *Checkpoint: a test event lands in Postgres without blocking a request.*

**Step 5. Expose the prompt API.**
Define the Pydantic schemas (`api/schemas/`) and implement `POST /api/prompt` with a stubbed response. Every request is logged to audit. *Checkpoint: a prompt submitted via curl returns a canned response and appears in `prompt_requests`.*

**Step 6. Add governance intake.**
Implement prompt normalization and enrichment (`governance/intake.py`) and policy tagging with safety directives (`governance/policy.py`). The reviewed prompt and governance metadata are logged. *Checkpoint: raw and reviewed prompt text both appear in the audit trail.*

**Step 7. Bring up the local LLM runtime.**
Implement `llm/runtime.py` with the single global `llama-cpp-python` instance created in the lifespan handler, plus `scripts/download_model` and the `models/` README. *Checkpoint: the service loads a GGUF model at startup and completes a direct prompt.*

**Step 8. Close the first end-to-end loop.**
Wire `POST /api/prompt` through governance → LLM → response, persisting the response and final output to audit. *Checkpoint: a real model-generated answer comes back from the API with a complete audit record — the minimal vertical slice works.*

## Phase 2 — Orchestration, frontend, and agents

**Step 9. Introduce the LangGraph main graph.**
Build `orchestration/graph.py` and the core nodes (prompt engineering, LLM review, respond), replacing the direct LLM call from step 8 with graph execution. Prompt templates live in `llm/prompts/`. *Checkpoint: same API behavior, now routed through the graph.*

**Step 10. Add the shared state store.**
Implement `state/store.py` for session, graph, and agent state with task queues. Graph nodes mutate state only through this package. Expose read APIs for session and run status. *Checkpoint: an in-flight prompt's progress is visible via an HTTP status endpoint.*

**Step 11. Scaffold the React frontend.**
Create the Vite app under `frontend/` with the chat UI (`Chat/`), the HTTP client (`api/client.ts`), and frontend state management. Develop against the Vite dev server proxying `/api`. *Checkpoint: a user can chat with LunaBlue from the browser in dev mode.*

**Step 12. Integrate the frontend build.**
Add `scripts/build_frontend` to build the React app into `backend/app/static` and mount it in FastAPI. *Checkpoint: one process serves both the UI and the API — the self-contained deployment shape from the architecture.*

**Step 13. Stream live state over WebSockets.**
Implement the pub/sub bridge (`state/events.py`), the WebSocket endpoint (`api/websocket.py`), and the frontend connection with polling fallback (`api/ws.ts`). *Checkpoint: prompt progress updates appear live in the UI without refresh.*

**Step 14. Run background agents.**
Implement the agent lifecycle contract (`orchestration/agents/base.py`), the background runner and task queue (`orchestration/runner.py`), and the agent-spawn graph node. Agent lifecycle events are written to `agent_events`. *Checkpoint: a prompt can spawn an agent that keeps working after the response returns.*

**Step 15. Surface agents in the UI.**
Add the agent status APIs (`/api/agents`, `/api/agents/{id}`) and the `AgentPanel/` and `StatusBar/` components, fed by WebSocket lifecycle updates. *Checkpoint: users see agent IDs, queue status, and last results live.*

## Phase 3 — Quality, hardening, and release

**Step 16. Build out the test suites.**
Create `tests/backend/` with a `conftest.py` that stubs the LLM runtime (no model file needed), covering routes, governance, graph execution, and audit; add frontend component tests. *Checkpoint: the full suite runs green in CI without a GPU or model download.*

**Step 17. Harden the runtime.**
Add error handling and timeouts around model execution and agent runs, readiness checks, config validation at startup, and the data retention and redaction safeguards called for in [Components/AUDIT.md](Components/AUDIT.md). *Checkpoint: the service degrades gracefully — bad prompts, model failures, and DB outages produce clean errors and audit entries, not crashes.*

**Step 18. Finish setup and release v1.0.**
Polish `scripts/setup`, verify the full clean-machine path (clone → setup → download model → migrate → build frontend → run), sync the docs with what was built, and tag the release. *Checkpoint: full capability — a new user reaches a working local assistant with live agents and a complete audit trail from a fresh clone.*

## Sequencing notes

- The order front-loads risk: the LLM runtime (step 7) and the end-to-end loop (step 8) are proven before any orchestration or UI investment.
- Every step after 8 keeps the system releasable; each checkpoint is a demoable state.
- Tests should be written alongside steps 2–15 where practical; step 16 consolidates them into a complete, CI-ready suite rather than being the first time tests exist.
