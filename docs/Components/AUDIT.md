# SQLite Log / Audit

## Purpose

This component provides persistent storage for the LunaBlue prompt lifecycle and governance audit trail. It ensures every prompt request, prompt response, and decision step is traceable outside the in-process runtime. Since Step 21 the store is a local SQLite file (`data/lunablue.db`, `sqlite+aiosqlite`) created automatically on first start — no database server, no Docker.

## Responsibilities

- store raw prompt requests and reviewed prompt text
- record prompt responses, LLM outputs, and final assistant outputs
- capture governance metadata, policy tags, and decision rationale
- track agent lifecycle events and state changes
- support troubleshooting, analytics, and compliance review

## Directory Mapping

This component lives in the `backend/app/audit/` package defined in [Architecture.md](../Architecture.md#directory-structure):

- `db.py` — SQLAlchemy engine and session management; the engine is created in the `main.py` lifespan handler, which also applies Alembic migrations automatically (`run_migrations`). Every SQLite connection gets the audit pragmas: `journal_mode=WAL`, `foreign_keys=ON`, `busy_timeout=5000`, `synchronous=FULL`.
- `models.py` — SQLAlchemy tables: `prompt_requests`, `prompt_responses`, `agent_events`, `sessions`; dialect-portable types (`JSON`, `TZDateTime` for aware-UTC round-trips over SQLite's naive storage).
- `service.py` — structured audit writer, decoupled from the request path.
- `redaction.py` — regex-based masking of secrets/PII applied before audit writes (Step 17; see [DataRetention.md](../DataRetention.md)).
- `retention.py` — deletes audit rows older than the configured per-table window; invoked by `scripts/retention`.
- `backend/migrations/` — Alembic migrations for the audit/state schema (`alembic.ini` at the backend root); the schema is owned by the Python service and applied automatically at startup.
- `scripts/migrate` — runs Alembic migrations manually (startup normally does this for you).
- `scripts/retention` — applies the retention policy (supports `--dry-run`); schedule with cron / Task Scheduler.

## Durability & concurrency (Step 21)

- **WAL mode** lets the readiness probe and audit reads proceed while the single background writer commits — neither blocks the other.
- **`synchronous=FULL`** fsyncs the WAL at every commit. With WAL, `NORMAL` could lose the most recently committed transactions on OS crash or power loss (never corruption); an audit log's job is to be on disk, so FULL wins. The writer batches up to 100 events per transaction, so the cost is roughly one fsync per batch. If profiling ever shows fsync pressure, `NORMAL` is the documented fallback.
- **`foreign_keys=ON`** is per-connection in SQLite; without it the schema's `ON DELETE CASCADE`/`SET NULL` clauses silently no-op.
- The database must live on a local disk — WAL is unsupported on network filesystems. WAL sibling files (`*.db-wal`, `*.db-shm`) appear next to the database and are gitignored.

## Build Approach

1. Define a dialect-portable schema in `models.py` for prompt audit records (`prompt_requests`, `prompt_responses`), agent events (`agent_events`), and session metadata (`sessions`), managed with Alembic migrations.
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
- Data retention and privacy safeguards (redaction and per-table retention windows, both configuration-driven) are documented in [DataRetention.md](../DataRetention.md).
