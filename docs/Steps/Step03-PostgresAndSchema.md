# Step 3 Prompt — Provision Postgres and the Schema

Use this prompt to execute Step 3 of [BuildPlan.md](../BuildPlan.md).

---

You are building **LunaBlue** (see `docs/Architecture.md` and `docs/Components/AUDIT.md`). Steps 1–2 delivered the repository skeleton and a runnable FastAPI service with health checks. `docker-compose.yml` already defines a Postgres service.

## Objective

Establish the Postgres persistence foundation: SQLAlchemy engine and session management, Alembic migrations, and the initial audit schema. Postgres is the primary durable database; runtime state stays in memory.

## Tasks

1. Add `sqlalchemy` (2.x), the async Postgres driver (`asyncpg`), `alembic`, and `greenlet` to `backend/pyproject.toml`.
2. Implement `backend/app/audit/db.py`:
   - Async SQLAlchemy engine created from `settings.database_url`.
   - Async session factory and a dependency/context helper for acquiring sessions.
   - Engine creation and disposal wired into the `main.py` lifespan handler (create on startup, dispose on shutdown).
3. Initialize Alembic in `backend/` (`alembic.ini` at the backend root, environment in `backend/migrations/`), configured to read the database URL from settings/environment rather than hardcoding it, and to support autogenerate against the models' metadata.
4. Write the first migration creating the four audit tables defined in `docs/Components/AUDIT.md`:
   - `sessions` — session id, user id, created/updated timestamps, metadata (JSONB).
   - `prompt_requests` — request id (PK), session FK, timestamp, user id, raw prompt text, reviewed prompt text, prompt version, governance flags/metadata (JSONB).
   - `prompt_responses` — id, request FK, timestamp, LLM output text, final output text, model identifier, token/timing metadata (JSONB).
   - `agent_events` — id, agent id, request FK (nullable), timestamp, event type, state, payload (JSONB).
   - Indexes on every table's timestamp column and on `agent_events.agent_id`, per the AUDIT.md implementation notes.
5. Create `scripts/migrate.ps1` and `scripts/migrate.sh` that run `alembic upgrade head` against the configured database.
6. Extend `GET /api/health` (or add `GET /api/health/ready`) to verify database connectivity with a trivial query.

## Constraints

- The schema is owned by the Python service; all schema changes go through Alembic migrations (per `docs/Components/AUDIT.md`).
- No table writes in this step beyond what migrations do — the audit writer is Step 4.
- Keep `audit/db.py` free of model or business logic; it owns only engine and session management.

## Verification

- `docker compose up -d postgres` then `scripts/migrate` creates all four tables and indexes (verify via `psql \dt` or equivalent).
- Running the migration twice is idempotent.
- `alembic downgrade base` cleanly drops the schema; `upgrade head` restores it.
- The readiness check returns healthy with Postgres up, and unhealthy (without crashing the service) with Postgres stopped.
