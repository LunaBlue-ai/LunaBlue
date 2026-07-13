# Step 4 Prompt — Build the Audit Service

Use this prompt to execute Step 4 of [BuildPlan.md](../BuildPlan.md).

---

You are building **LunaBlue** (see `docs/Architecture.md` and `docs/Components/AUDIT.md`). Steps 1–3 delivered the repo skeleton, a runnable FastAPI service, and a migrated Postgres schema with tables `sessions`, `prompt_requests`, `prompt_responses`, and `agent_events`. `audit/db.py` provides the async engine and session factory.

## Objective

Implement the audit layer: SQLAlchemy models mirroring the schema, and a structured audit writer that records events **off the hot path** — an audit write must never block or fail a user request.

## Tasks

1. Implement `backend/app/audit/models.py` with SQLAlchemy 2.0 declarative models for the four tables, exactly matching the Step 3 migration (verify with Alembic autogenerate producing an empty diff).
2. Implement `backend/app/audit/service.py`:
   - Typed event dataclasses or Pydantic models for each auditable event: `PromptRequestEvent` (raw prompt, reviewed prompt, governance metadata), `PromptResponseEvent` (LLM output, final output, model/timing metadata), `AgentEvent` (agent id, event type, state, payload), `SessionEvent`.
   - An `AuditService` with methods like `record_prompt_request(...)`, `record_prompt_response(...)`, `record_agent_event(...)` that **enqueue** events onto an internal `asyncio.Queue` and return immediately.
   - A background consumer task (started in the lifespan handler, drained and stopped cleanly on shutdown) that batches or serially writes queued events using its own sessions.
   - Failure policy: a failed write logs the error with the event payload and continues; it never raises into the request path. Include a bounded queue with a documented overflow policy (log-and-drop oldest or newest — choose and document).
3. Wire `AuditService` into the application: constructed in the lifespan handler, exposed via FastAPI dependency injection so routes and (later) graph nodes can request it.
4. Add a temporary debug route or a small integration test that emits one of each event type and confirms the rows land in Postgres.

## Constraints

- Audit writes are decoupled from the request path (per `docs/Components/AUDIT.md`) — no direct DB writes from route handlers.
- Only `audit/` touches SQLAlchemy models and sessions; other packages interact through `AuditService` event methods.
- Store enough context for replay and debugging: request id, timestamps (UTC), user id, prompt version, agent id, and governance flags must all be populated when available.

## Verification

- Emitting a `PromptRequestEvent` returns in microseconds (no DB round-trip on the caller's path) and the row appears in `prompt_requests` shortly after.
- Killing Postgres while emitting events produces logged errors — the service keeps serving requests and does not crash.
- Clean shutdown drains the queue: events emitted just before shutdown are persisted.
- Alembic autogenerate against `models.py` yields no schema diff.
