"""Core fixtures for the consolidated backend suite (Step 16).

The suite runs on any machine without a GPU, a model file, or manual setup:

- The LLM is always :class:`tests.backend.fakes.FakeLlamaRuntime`; importing
  ``llama_cpp`` anywhere during the run is a hard error (see the meta-path
  blocker below), so no test can accidentally depend on the real runtime.
- Database tests (Step 21: SQLite) depend — directly or via
  ``audit_service`` — on :func:`audit_db`, which targets a per-session
  temp-file SQLite database, migrates it with Alembic once per session, and
  deletes the audit rows after every test. SQLite ships with Python, so
  these tests always run — there is no skip path.
"""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.audit import db
from app.audit.service import AuditService
from app.state.events import EventBus
from app.state.store import StateStore
from tests.backend.fakes import FakeAuditService, FakeLlamaRuntime, make_app

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"


class _LlamaCppImportBlocker:
    """Fail loudly if anything tries to import ``llama_cpp`` during tests.

    Enforces the Step 16 constraint that the fake runtime is the only runtime
    available to the suite: no test may load a real model, and the suite must
    pass with ``llama-cpp-python`` not even installed.
    """

    def find_spec(self, fullname, path=None, target=None):
        if fullname == "llama_cpp" or fullname.startswith("llama_cpp."):
            raise ImportError(
                "llama_cpp must never be imported in tests — inject "
                "tests.backend.fakes.FakeLlamaRuntime instead"
            )
        return None


sys.meta_path.insert(0, _LlamaCppImportBlocker())


# -- LLM runtime / app wiring -------------------------------------------------


@pytest.fixture
def fake_runtime() -> FakeLlamaRuntime:
    """A loaded :class:`FakeLlamaRuntime`; script it via ``.fake``."""
    runtime = FakeLlamaRuntime()
    runtime.load()
    return runtime


@pytest.fixture
def fake_audit() -> FakeAuditService:
    """In-memory audit recorder for tests that don't need the database."""
    return FakeAuditService()


@pytest.fixture
def app(fake_audit, fake_runtime):
    """An app built via ``create_app()`` and wired like the lifespan, with the
    fake audit service and fake runtime injected (see ``fakes.make_app``)."""
    return make_app(fake_audit, fake_runtime)


@pytest.fixture
async def client(app) -> AsyncClient:
    """Async HTTP client against the fake-wired app."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as http_client:
        yield http_client


# -- shared state -------------------------------------------------------------


@pytest.fixture
def state_store() -> StateStore:
    """A fresh in-memory state store."""
    return StateStore(max_finished_runs=64)


@pytest.fixture
def event_bus(state_store) -> EventBus:
    """A fresh bus receiving ``state_store``'s mutations."""
    bus = EventBus()
    state_store.set_notify(bus.publish)
    return bus


# -- SQLite (audit) ------------------------------------------------------------


@pytest.fixture(scope="session")
def test_database_url(tmp_path_factory) -> str:
    """URL of the suite's database: a per-session temp SQLite file.

    ``LUNABLUE_TEST_DATABASE_URL`` still overrides it for one-off runs
    against another database file.
    """
    override = os.environ.get("LUNABLUE_TEST_DATABASE_URL")
    if override:
        return override
    path = tmp_path_factory.mktemp("db") / "test.db"
    return f"sqlite+aiosqlite:///{path.as_posix()}"


@pytest.fixture(scope="session")
def migrated_database(test_database_url) -> str:
    """URL of the test database, migrated to Alembic head once per session."""
    config = Config()
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    # migrations/env.py reads -x db_url=... ahead of application settings.
    config.cmd_opts = SimpleNamespace(x=[f"db_url={test_database_url}"])
    command.upgrade(config, "head")
    return test_database_url


@pytest.fixture
async def audit_db(migrated_database) -> str:
    """Bind the process-wide engine to the migrated test database for one
    test; the audit rows are deleted afterwards so state never leaks."""
    db.init_engine(migrated_database)
    try:
        yield migrated_database
    finally:
        try:
            # Children first: SQLite has no TRUNCATE ... CASCADE.
            async with db.session_scope() as session:
                # The sqlite-vec virtual table exists only once a vector
                # test ran ensure_schema against the shared database.
                vec_exists = (
                    await session.execute(
                        text(
                            "SELECT 1 FROM sqlite_master WHERE type='table' "
                            "AND name='vec_prompt_embeddings'"
                        )
                    )
                ).scalar()
                if vec_exists:
                    await session.execute(
                        text("DELETE FROM vec_prompt_embeddings")
                    )
                for table in (
                    "prompt_embeddings",
                    "agent_events",
                    "prompt_responses",
                    "prompt_requests",
                    "sessions",
                ):
                    await session.execute(text(f"DELETE FROM {table}"))
        finally:
            await db.dispose_engine()


@pytest.fixture
async def audit_service(audit_db) -> AuditService:
    """A started :class:`AuditService` writing to the test database.

    ``await audit_service.flush()`` drains everything recorded so far;
    teardown closes the service (which drains once more).
    """
    service = AuditService()
    service.start()
    yield service
    await service.close()
