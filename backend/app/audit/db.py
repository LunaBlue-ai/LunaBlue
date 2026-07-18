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

import logging
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

logger = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None

_SQLITE_PRAGMAS = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA foreign_keys=ON",
    "PRAGMA busy_timeout=5000",
    "PRAGMA synchronous=FULL",
)

# Whether the sqlite-vec extension loaded on this engine's connections.
# None = no sqlite engine initialized yet; embedding search requires True.
_vec_loaded: bool | None = None
_vec_load_warned = False


def vec_available() -> bool:
    """Whether connections carry the sqlite-vec extension (vec0 tables)."""
    return bool(_vec_loaded)


def _load_vec_extension(dbapi_conn: Any) -> None:
    """Load sqlite-vec into a new connection; degrade quietly on failure.

    The vector store is an enhancement: a Python build without
    ``enable_load_extension`` (or a broken sqlite-vec install) must not
    prevent the audit store from working.

    The sqlite3 connection lives in aiosqlite's worker thread
    (``check_same_thread`` enforced), so the extension calls must go
    through aiosqlite's coroutine API rather than touching the raw
    connection directly. The connect event runs inside SQLAlchemy's
    greenlet adaptation, so ``await_only`` bridges the coroutines here.
    """
    global _vec_loaded, _vec_load_warned
    try:
        import sqlite_vec
        from sqlalchemy.util import await_only

        raw = getattr(dbapi_conn, "driver_connection", dbapi_conn)
        await_only(raw.enable_load_extension(True))
        try:
            await_only(raw.load_extension(sqlite_vec.loadable_path()))
        finally:
            await_only(raw.enable_load_extension(False))
        _vec_loaded = True
    except Exception as exc:
        _vec_loaded = False
        if not _vec_load_warned:
            _vec_load_warned = True
            logger.warning(
                "sqlite-vec extension failed to load (%s: %s) - embedding "
                "storage and /api/search are disabled. The audit store is "
                "unaffected.",
                type(exc).__name__,
                exc,
            )


def _set_sqlite_pragmas(dbapi_conn: Any, _record: Any) -> None:
    cursor = dbapi_conn.cursor()
    for pragma in _SQLITE_PRAGMAS:
        cursor.execute(pragma)
    cursor.close()
    _load_vec_extension(dbapi_conn)


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
    global _engine, _session_factory, _vec_loaded
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
    _vec_loaded = None


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
