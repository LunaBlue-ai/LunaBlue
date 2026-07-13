# Step 10 Prompt — Add the Shared State Store

Use this prompt to execute Step 10 of [BuildPlan.md](../BuildPlan.md).

---

You are building **LunaBlue** (see `docs/Architecture.md`). Steps 1–9 delivered the full prompt loop through a LangGraph main graph. There is not yet a shared runtime state store — graph state lives only inside each graph run.

## Objective

Implement the in-memory shared state store: the single source of truth for sessions, in-flight prompt runs, and (from Step 14) agents and task queues. Expose read APIs so progress is observable over HTTP. This store is what WebSockets will stream from in Step 13.

## Tasks

1. Implement `backend/app/state/store.py`:
   - A `StateStore` holding: active sessions (id, user, created/last-activity), prompt runs (request id → status such as `received` / `governance` / `engineering` / `reviewing` / `responding` / `completed` / `failed`, current node, timings, result summary), and an agent registry with task queues (structures defined now, populated in Step 14).
   - Async-safe mutation methods (`start_run`, `update_run_phase`, `complete_run`, `fail_run`, session upsert/touch) guarded appropriately for concurrent access.
   - Read methods returning immutable snapshots (copies or frozen views), never live internal references.
   - Bounded retention: completed runs are kept for a configurable window/count and then evicted — Postgres audit is the durable record, the store is live state only (per `docs/Architecture.md`).
   - Constructed in the lifespan handler and exposed via dependency injection.
2. Instrument the graph: entering each node updates the run's phase in the store (wire this via graph callbacks/hooks or thin node wrappers — keep nodes themselves clean).
3. Implement read routes in `backend/app/api/routes/` with schemas in `api/schemas/`:
   - `GET /api/runs/{request_id}` — full run status snapshot.
   - `GET /api/sessions/{session_id}` — session metadata plus its recent runs.
4. Prepare for Step 13 without implementing it: every store mutation funnels through a single internal notify point (a no-op hook for now) so `state/events.py` can attach with no store rewrite.

## Constraints

- Graph nodes and routes mutate state **only** through `StateStore` methods — no shared dicts passed around (per the structural rules in `docs/Architecture.md`).
- The store knows nothing about WebSockets, HTTP, or the audit layer.
- Snapshots must be cheap; status polling must not contend with graph execution.

## Verification

- Submit a prompt, then poll `GET /api/runs/{request_id}` during execution: the phase visibly advances (governance → engineering → reviewing → responding → completed).
- `GET /api/sessions/{id}` lists the session's runs with correct statuses.
- A failed run shows `failed` with the error summary in its snapshot.
- Concurrent prompt submissions maintain consistent, independent run states.
- Evicted (old) runs return 404 from the run endpoint while remaining fully present in Postgres audit.
