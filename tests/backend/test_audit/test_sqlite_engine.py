"""Tests for the SQLite engine behavior (Step 21): pragmas, FK enforcement,
timezone round-trips, and the resolved database URL."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.audit import db
from app.audit.models import (
    AgentEvent,
    PromptRequest,
    PromptResponse,
    Session,
    TZDateTime,
)
from app.config import _REPO_ROOT, Settings


def make_settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


# -- TZDateTime ---------------------------------------------------------------


def test_tzdatetime_bind_normalizes_aware_values_to_naive_utc():
    tz = TZDateTime()
    eastern = timezone(timedelta(hours=-5))
    aware = datetime(2026, 7, 17, 7, 30, tzinfo=eastern)
    stored = tz.process_bind_param(aware, None)
    assert stored == datetime(2026, 7, 17, 12, 30)
    assert stored.tzinfo is None


def test_tzdatetime_bind_passes_naive_and_none_through():
    tz = TZDateTime()
    naive = datetime(2026, 7, 17, 12, 30)
    assert tz.process_bind_param(naive, None) == naive
    assert tz.process_bind_param(None, None) is None


def test_tzdatetime_result_returns_aware_utc():
    tz = TZDateTime()
    restored = tz.process_result_value(datetime(2026, 7, 17, 12, 30), None)
    assert restored == datetime(2026, 7, 17, 12, 30, tzinfo=timezone.utc)
    assert tz.process_result_value(None, None) is None


# -- engine pragmas -----------------------------------------------------------


async def test_sqlite_engine_sets_the_audit_pragmas(tmp_path):
    engine = db.init_engine(
        f"sqlite+aiosqlite:///{(tmp_path / 'pragmas.db').as_posix()}"
    )
    try:
        async with engine.connect() as conn:
            journal = (await conn.execute(text("PRAGMA journal_mode"))).scalar()
            fk = (await conn.execute(text("PRAGMA foreign_keys"))).scalar()
            sync = (await conn.execute(text("PRAGMA synchronous"))).scalar()
        assert journal == "wal"
        assert fk == 1
        assert sync == 2  # FULL
    finally:
        await db.dispose_engine()


async def test_foreign_key_ondelete_is_enforced(audit_db):
    """PRAGMA foreign_keys=ON makes the schema's ON DELETE clauses real:
    deleting a request cascades its responses and nulls agent_events'
    request_id (models.py ondelete)."""
    now = datetime.now(timezone.utc)
    async with db.session_scope() as session:
        # Flush between parents and children: the models carry no ORM
        # relationships, so the unit of work cannot infer insert order.
        session.add(Session(session_id="s-fk", created_at=now, updated_at=now))
        await session.flush()
        session.add(
            PromptRequest(
                request_id="r-fk",
                session_id="s-fk",
                timestamp=now,
                raw_prompt="hello",
            )
        )
        await session.flush()
        session.add(
            PromptResponse(request_id="r-fk", timestamp=now, llm_output="hi")
        )
        session.add(
            AgentEvent(
                agent_id="a-fk",
                request_id="r-fk",
                timestamp=now,
                event_type="spawned",
            )
        )

    async with db.session_scope() as session:
        # Timestamps round-trip as aware UTC through TZDateTime.
        fetched = await session.get(Session, "s-fk")
        assert fetched.created_at.tzinfo is not None
        assert abs((fetched.created_at - now).total_seconds()) < 1

    async with db.session_scope() as session:
        await session.execute(
            text("DELETE FROM prompt_requests WHERE request_id='r-fk'")
        )

    async with db.session_scope() as session:
        responses = (
            await session.execute(
                text("SELECT count(*) FROM prompt_responses")
            )
        ).scalar()
        assert responses == 0  # ondelete=CASCADE fired
        orphaned = (
            await session.execute(
                text(
                    "SELECT request_id FROM agent_events WHERE agent_id='a-fk'"
                )
            )
        ).scalar()
        assert orphaned is None  # ondelete=SET NULL fired


# -- startup migration --------------------------------------------------------


async def test_run_migrations_creates_the_schema_from_a_worker_thread(tmp_path):
    """The lifespan mechanism: run_migrations via asyncio.to_thread against a
    brand-new file creates the data dir, the database, and all tables —
    exactly what first boot on a clean machine does."""
    import asyncio

    url = f"sqlite+aiosqlite:///{(tmp_path / 'fresh' / 'app.db').as_posix()}"
    await asyncio.to_thread(db.run_migrations, url)
    # Idempotent: a second boot is a no-op, not an error.
    await asyncio.to_thread(db.run_migrations, url)

    engine = db.init_engine(url)
    try:
        async with engine.connect() as conn:
            names = (
                await conn.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table'")
                )
            ).scalars()
            tables = set(names)
        assert {
            "sessions",
            "prompt_requests",
            "prompt_responses",
            "agent_events",
            "alembic_version",
        } <= tables
    finally:
        await db.dispose_engine()


# -- resolved database URL ----------------------------------------------------


def test_default_database_url_resolves_to_repo_root_data_dir():
    settings = make_settings()
    path = settings.resolved_database_path
    assert path is not None
    assert path.is_absolute()
    assert path == (_REPO_ROOT / "data" / "lunablue.db").resolve()
    resolved = settings.resolved_database_url
    assert resolved.startswith("sqlite+aiosqlite:///")
    assert resolved.endswith("/data/lunablue.db")
    assert "\\" not in resolved  # forward slashes even on Windows


def test_absolute_database_url_passes_through(tmp_path):
    url = f"sqlite+aiosqlite:///{(tmp_path / 'x.db').as_posix()}"
    settings = make_settings(database_url=url)
    assert settings.resolved_database_url == url
    assert settings.resolved_database_path == tmp_path / "x.db"


def test_non_sqlite_url_has_no_database_path():
    settings = make_settings(
        database_url="postgresql+asyncpg://u:p@localhost/db"
    )
    assert settings.resolved_database_path is None
    assert settings.resolved_database_url == settings.database_url
