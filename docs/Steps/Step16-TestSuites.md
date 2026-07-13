# Step 16 Prompt — Build Out the Test Suites

Use this prompt to execute Step 16 of [BuildPlan.md](../BuildPlan.md).

---

You are building **LunaBlue** (see `docs/Architecture.md`). Steps 1–15 delivered the full-featured system: prompt loop through the LangGraph main graph, governance, audit, shared state with WebSocket streaming, background agents, and the React UI with agent visibility. Tests written along the way (if any) are scattered; this step consolidates them into a complete, CI-ready suite.

## Objective

Build the consolidated test suites under `tests/`, runnable on any machine or CI runner **without a GPU, a model file, or manual setup**. The LLM runtime is stubbed; everything else is exercised for real as far as practical.

## Tasks

1. Implement `tests/backend/conftest.py` with the core fixtures:
   - `FakeLlamaRuntime` — drop-in for `LlamaRuntime`: deterministic canned/scripted responses (configurable per test), records received prompts for assertions, simulates latency and failure on demand. Provided via the app's dependency injection so **no test loads a real model**.
   - App fixture — builds the app via `create_app()` with test settings and the fake runtime; async HTTP client (httpx) against it.
   - Test database — a dedicated Postgres (docker-compose test service or testcontainers), migrated via Alembic per session and truncated between tests; skip-marked with a clear message if Docker is unavailable.
   - Fixtures for a drained `AuditService` (helper to await queue flush) and a fresh `StateStore`/`EventBus`.
2. `tests/backend/test_api/` — route-level tests: prompt submission happy path and validation failures, run/session status endpoints, agent list/detail/cancel, health/readiness, SPA fallback vs. `/api` 404 behavior, and WebSocket tests (connect, snapshot message, live `run_updated` events, `ws_enabled=false`).
3. `tests/backend/test_governance/` — intake normalization cases, prompt versioning, policy tagging, strict-mode rejection with audit assertions.
4. `tests/backend/test_orchestration/` — each graph node as a unit against hand-built state and the fake runtime; full graph runs asserting state transitions and decision metadata; agent spawn flow; `AgentRunner` lifecycle including failure isolation and cancellation.
5. `tests/backend/test_audit/` — event enqueue/flush semantics, off-hot-path guarantee (writer failure doesn't propagate), model/migration parity (autogenerate empty diff), agent-history reconstruction from `agent_events`.
6. Frontend tests (Vitest + React Testing Library, colocated in `frontend/src` or `tests/frontend` — follow the repo's existing choice): chat submit/pending/error rendering, reducer logic for run and agent events, AgentPanel state badges and live updates from simulated WS events, StatusBar connectivity states.
7. CI workflow (e.g. GitHub Actions): lint + type-check + backend suite (with Postgres service) + frontend build and tests. Document the local commands (`pytest`, `npm test`) in the README.

## Constraints

- No test may require a GGUF file, GPU, or network model download — enforce by making the fake runtime the only runtime importable in test settings.
- Tests must be order-independent and parallel-safe (isolated DB state per test).
- Don't chase coverage numbers; cover the contracts each step's Verification section promised.

## Verification

- `pytest` passes green from a clean checkout with only Docker (for Postgres) available — no model file present.
- Frontend suite and `npm run build` pass green.
- The CI pipeline runs the full suite on push and fails on a deliberately introduced regression (spot-check one).
- Total backend suite runtime stays fast enough for pre-commit use (target: under a few minutes).
