"""SQLAlchemy engine and session management for the audit store.

This module owns only connectivity: the async engine lives for the process
lifetime (created/disposed by the ``main.py`` lifespan handler), and sessions
are handed out per unit of work. Table definitions live in ``models.py``.

Step 21 (SQLite): for ``sqlite+aiosqlite`` URLs the engine sets the pragmas
the audit store depends on, on every new connection:

- ``journal_mode=WAL`` — readers (readiness probe, ``fetch_agent_events``)
  never block on the single audit writer, and vice versa.
- ``foreign_keys=ON`` — SQLite only honors the schema's ``ON DELETE``
  clauses when this per-connection pragma is set.
- ``busy_timeout=5000`` — writers briefly contending (e.g. the standalone
  retention run against a live app) wait instead of failing.
- ``synchronous=FULL`` — the WAL is fsynced at each commit. With WAL,
  ``NORMAL`` could lose the most recently committed transactions on power
  loss; this database *is* the audit log, so durability wins. The writer
  batches up to 100 events per transaction, so this costs roughly one fsync
  per batch.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None

_SQLITE_PRAGMAS = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA foreign_keys=ON",
    "PRAGMA busy_timeout=5000",
    "PRAGMA synchronous=FULL",
)


def _set_sqlite_pragmas(dbapi_conn: Any, _record: Any) -> None:
    cursor = dbapi_conn.cursor()
    for pragma in _SQLITE_PRAGMAS:
        cursor.execute(pragma)
    cursor.close()


def run_migrations(database_url: str) -> None:
    """Apply Alembic migrations to head (Step 21: called from the lifespan).

    Synchronous by design: ``alembic.command.upgrade`` runs
    ``migrations/env.py``, which itself calls ``asyncio.run`` — so this
    helper must execute on a thread with no running event loop. The lifespan
    calls it via ``asyncio.to_thread``. Paths are absolute (derived from this
    file), never CWD-relative: uvicorn may be launched from anywhere.
    """
    from alembic import command
    from alembic.config import Config

    backend_dir = Path(__file__).resolve().parents[2]
    # A bare Config (no alembic.ini): loading the ini would make env.py run
    # fileConfig(), silently reconfiguring the application's logging. The
    # ini only carries logging + file-template settings; upgrades need just
    # the script location.
    config = Config()
    config.set_main_option("script_location", str(backend_dir / "migrations"))
    # migrations/env.py reads this ahead of application settings.
    config.attributes["db_url"] = database_url
    command.upgrade(config, "head")


def init_engine(database_url: str) -> AsyncEngine:
    """Create the process-wide engine and session factory.

    Called once from the application lifespan startup. Connections are
    established lazily, so this succeeds even before the database file
    exists (SQLite creates it on first connect).
    """
    global _engine, _session_factory
    if make_url(database_url).get_backend_name() == "sqlite":
        # No pool_pre_ping: there is no network to ping, and the pragma
        # listener below runs on every new connection.
        _engine = create_async_engine(database_url)
        event.listen(_engine.sync_engine, "connect", _set_sqlite_pragmas)
    else:
        _engine = create_async_engine(database_url, pool_pre_ping=True)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


async def dispose_engine() -> None:
    """Close all pooled connections; called from lifespan shutdown."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


def get_engine() -> AsyncEngine:
    """Return the live engine, failing loudly if startup never ran."""
    if _engine is None:
        raise RuntimeError("Database engine not initialized (init_engine)")
    return _engine


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Context manager yielding a session that commits on success and
    rolls back on error."""
    if _session_factory is None:
        raise RuntimeError("Database engine not initialized (init_engine)")
    async with _session_factory() as session:
        async with session.begin():
            yield session


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a session; callers manage commits."""
    if _session_factory is None:
        raise RuntimeError("Database engine not initialized (init_engine)")
    async with _session_factory() as session:
        yield session
