# Changelog

## Unreleased

- GPU visibility: the runtime now probes whether the installed
  `llama-cpp-python` build supports GPU offload. When `LLM_GPU_LAYERS` != 0 on
  a CPU-only build (which silently ignores it), startup logs a warning, and
  `model_info` / `/api/health/ready` expose `gpu_offload_supported`. Setup
  scripts
  print a hint when an NVIDIA GPU is detected; backend/README.md documents the
  CUDA wheel install (match the wheel's CUDA series to the installed toolkit).

## v1.0.0 — 2026-07-15

First release. LunaBlue reaches full capability: a fresh clone on a machine
with only Python, Node, and Docker becomes a working local assistant — live
agents, streaming UI, and a complete audit trail — using nothing but the
README quickstart. Built in 18 steps across three phases
([docs/BuildPlan.md](docs/BuildPlan.md)).

### Phase 1 — Foundation and the first prompt loop (Steps 1–8)

- Repository scaffold, FastAPI app factory, pydantic-settings configuration,
  and health endpoint.
- Postgres via docker-compose, SQLAlchemy engine, and Alembic migrations for
  the audit schema (`prompt_requests`, `prompt_responses`, `agent_events`,
  `sessions`).
- Structured audit service writing off the hot path.
- `POST /api/prompt` with a validated Pydantic contract; every request and
  response audited.
- Governance intake: prompt normalization, enrichment, policy tags, and
  safety directives, with raw and reviewed text both in the audit trail.
- In-process LLM runtime: one global `llama-cpp-python` instance loaded at
  startup, `scripts/download_model` for the default GGUF (Phi-3-mini Q4).
- First end-to-end loop: prompt → governance → local model → audited answer.

### Phase 2 — Orchestration, frontend, and agents (Steps 9–15)

- LangGraph main graph: prompt engineering → LLM review → agent spawn →
  respond, with prompt templates in `llm/prompts/`.
- Shared in-memory state store; run progress readable over HTTP.
- React (Vite) chat UI, served as static files by the same FastAPI process
  (`scripts/build_frontend`).
- Live state over WebSockets (`/ws`): snapshot on connect, then run-phase and
  agent lifecycle events, with an automatic polling fallback in the UI.
- Background agents: lifecycle contract, async runner and task queue, the
  built-in research agent, and lifecycle events persisted to `agent_events`.
- Agent UI: AgentPanel with live states and expandable event detail; StatusBar
  with connectivity, live channel, model status, and active-agent count.

### Phase 3 — Quality, hardening, and release (Steps 16–18)

- Consolidated test suites: 190+ backend tests (repo root, LLM faked, real
  Postgres exercised when available) and Vitest/RTL frontend tests; CI runs
  lint, both suites, type-check, and build on every push.
- Hardening: fail-fast startup validation; a `{code, message, request_id,
  detail}` error taxonomy that never leaks internals; generation timeouts and
  a busy guard; agent step/time bounds; WebSocket heartbeats and overflow
  resync; per-dependency readiness at `/api/health/ready`; audit secret/PII
  redaction and retention windows (`scripts/retention`).
- Release: idempotent `scripts/setup` with prerequisite checks, the verified
  clean-machine quickstart in the README, documentation synchronized with the
  code as built, and the version (1.0.0) surfaced by `/api/health` and the
  UI StatusBar.

### Known limitations

Single-node, single-process; one model at a time with serial generations
(the busy guard sheds excess load); in-memory session state (audit trail
survives restarts, live sessions do not); no authentication — binds to
`127.0.0.1` for one local user.
