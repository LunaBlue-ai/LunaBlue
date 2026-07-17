# Step 21 Prompt — Migrate the Audit Database to SQLite

Use this prompt to execute Step 21 (post-v1.0). Supersedes the Postgres/Docker database story from [Step03-PostgresAndSchema.md](Step03-PostgresAndSchema.md).

---

You are migrating **LunaBlue**'s only durable store — the audit database (`sessions`, `prompt_requests`, `prompt_responses`, `agent_events`) — from Postgres 16 in Docker to a file-based SQLite database, removing Docker as a prerequisite entirely: end users install nothing and start nothing.

## Objective

Replace `postgresql+asyncpg` with **`sqlite+aiosqlite:///data/lunablue.db`** (relative path anchored at the repo root, mirroring `resolved_model_path`), keep the full audit/logging functionality and schema shape, and make first boot self-contained: the app lifespan creates the data directory and runs Alembic to head automatically.

## Key decisions

- **Concurrency/durability**: every SQLite connection gets `PRAGMA journal_mode=WAL` (readers never block the single audit writer), `foreign_keys=ON` (SQLite only honors the schema's `ON DELETE` clauses with this per-connection pragma), `busy_timeout=5000`, and **`synchronous=FULL`** — with WAL, `NORMAL` can lose the most recent commits on power loss, and this database *is* the audit log; the writer batches ≤100 events per transaction, so FULL costs ~one fsync per batch. Set via a `connect` event listener in `audit/db.py::init_engine`.
- **Types**: `JSONB` → portable `sqlalchemy.JSON` (no JSONB operators were used); `BigInteger` autoincrement PKs → `BigInteger().with_variant(Integer, "sqlite")` (SQLite autoincrement needs `INTEGER PRIMARY KEY`); all timestamps → a `TZDateTime` TypeDecorator that stores naive UTC and returns aware UTC, keeping retention cutoff comparisons and API timestamps correct with zero caller changes.
- **Upsert**: the session upsert switches `sqlalchemy.dialects.postgresql.insert` → `sqlalchemy.dialects.sqlite.insert` — `on_conflict_do_update`/`.excluded` are API-identical.
- **Schema authority stays Alembic**: revision `0001` rewritten in place as portable DDL (`CURRENT_TIMESTAMP` defaults instead of `now()`); the lifespan runs `upgrade head` via `asyncio.to_thread` (env.py drives its own `asyncio.run`, so it must execute on a thread without a running loop) using a bare `Config` (loading alembic.ini would let env.py's `fileConfig` clobber application logging). `scripts/migrate.*` remain for manual use.
- **Validation inverted**: `startup.py::_check_database_url` now requires `sqlite+aiosqlite` and write-probes the parent directory; `check_database_connects` (SELECT 1) is unchanged and now validates file-create + query.
- **Tests never skip**: conftest targets a per-session temp SQLite file; the probe/skip machinery and `LUNABLUE_TEST_REQUIRE_DB` are gone; teardown is children-first `DELETE FROM` (SQLite has no `TRUNCATE ... CASCADE`); CI runs with no database service.
- **Data policy — start fresh**: no data is copied from Postgres. The old Docker volume `lunablue_pgdata` is untouched and remains the rollback artifact (re-create a postgres container mounting it to read the history); delete it manually (`docker volume rm lunablue_pgdata`) once comfortable. Anyone wanting history in SQLite can run a one-off copy in FK order (sessions → prompt_requests → prompt_responses → agent_events); JSONB values deserialize to the same structures `JSON` serializes, and BigInteger ids fit SQLite's 64-bit INTEGER.

## Removed

`docker-compose.yml` (it was entirely database infrastructure), the Docker prerequisite and compose steps in `scripts/setup.*` and the README quickstart, the CI `postgres:16` service, and the `asyncpg` dependency (replaced by `aiosqlite`).

## Caveats

- WAL creates `-wal`/`-shm` sibling files next to the database (gitignored). WAL is unsupported on network filesystems — the database is designed to live on a local disk.
- Multi-process deployments would race the startup migration; single-process uvicorn is the deployment model.

## Verification

- Full backend suite passes twice back-to-back with Docker not running and zero skips — including the Alembic autogenerate parity test against SQLite, PRAGMA/FK-cascade tests, TZDateTime round-trips, and the thread-based startup-migration test.
- Fresh boot: delete `data/lunablue.db`, start uvicorn — the file (+ WAL siblings) appears, readiness reports the database healthy, and a prompt's audit chain lands in the file.
- `scripts/retention.*` runs standalone against the file; `scripts/migrate.*` still works manually.
