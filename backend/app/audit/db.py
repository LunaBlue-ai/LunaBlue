"""SQLAlchemy engine and session management for the audit store.

This module owns only connectivity: the async engine lives for the process
lifetime (created/disposed by the ``main.py`` lifespan handler), and sessions
are handed out per unit of work. Table definitions live in ``models.py``.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_engine(database_url: str) -> AsyncEngine:
    """Create the process-wide engine and session factory.

    Called once from the application lifespan startup. Connections are
    established lazily, so this succeeds even if Postgres is down.
    """
    global _engine, _session_factory
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
