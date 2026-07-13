# Postgres Log / Audit

## Purpose

This component provides persistent storage for the LunaBlue prompt lifecycle and governance audit trail. It ensures every prompt request, prompt response, and decision step is traceable outside the in-process runtime.

## Responsibilities

- store raw prompt requests and reviewed prompt text
- record prompt responses, LLM outputs, and final assistant outputs
- capture governance metadata, policy tags, and decision rationale
- track agent lifecycle events and state changes
- support troubleshooting, analytics, and compliance review

## Directory Mapping

This component lives in the `backend/app/audit/` package defined in [Architecture.md](../Architecture.md#directory-structure):

- `db.py` — SQLAlchemy engine and session management; the engine is created in the `main.py` lifespan handler.
- `models.py` — SQLAlchemy tables: `prompt_requests`, `prompt_responses`, `agent_events`, `sessions`.
- `service.py` — structured audit writer, decoupled from the request path.
- `backend/migrations/` — Alembic migrations for the audit/state schema (`alembic.ini` at the backend root); the schema is owned by the Python service.
- `scripts/migrate` — runs Alembic migrations against Postgres; `docker-compose.yml` provides a local Postgres for development.

## Build Approach

1. Define a Postgres schema in `models.py` for prompt audit records (`prompt_requests`, `prompt_responses`), agent events (`agent_events`), and session metadata (`sessions`), managed with Alembic migrations.
2. Use SQLAlchemy for the engine, session management, and data access (`db.py`).
3. Add a backend audit service (`service.py`) that writes structured prompt events after each request.
4. Include fields for request id, timestamp, user id, prompt version, reviewed prompt, response text, agent id, and governance flags.
5. Build optional admin APIs or dashboards for querying prompt and agent audit history.
6. Document data retention and privacy safeguards for stored prompt content.

## Implementation Notes

- Use indexes on request timestamp and agent id for efficient retrieval.
- Keep audit writes decoupled from the main runtime path: `service.py` accepts structured events and writes them off the hot path (background task or queue).
- Separate tables or event types for prompt requests, prompt responses, and agent actions.
- Store enough context for replay and debugging without requiring full session reconstruction.
- Encrypt or redact sensitive prompt data if the system handles private inputs.
