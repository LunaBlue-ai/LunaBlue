"""Core fixtures for the consolidated backend suite (Step 16).

The suite runs on any machine without a GPU, a model file, or manual setup:

- The LLM is always :class:`tests.backend.fakes.FakeLlamaRuntime`; importing
  ``llama_cpp`` anywhere during the run is a hard error (see the meta-path
  blocker below), so no test can accidentally depend on the real runtime.
- Tests that need Postgres depend (directly or via ``audit_service``) on
  :func:`audit_db`, which targets the throwaway docker-compose test database,
  migrates it with Alembic once per session, and truncates the audit tables
  after every test. Without Docker those tests skip with instructions; the
  rest of the suite still runs.
"""

import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.audit import db
from app.audit.service import AuditService
from app.state.events import EventBus
from app.state.store import StateStore
from tests.backend.fakes import FakeAuditService, FakeLlamaRuntime, make_app

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"

# The docker-compose `postgres-test` service (profile "test"). CI points this
# at its own service container via the environment variable.
TEST_DATABASE_URL = os.environ.get(
    "LUNABLUE_TEST_DATABASE_URL",
    "postgresql+asyncpg://lunablue_test:lunablue_test@localhost:55432/lunablue_test",
)

_POSTGRES_HINT = (
    "Test Postgres unavailable — start it with "
    "`docker compose --profile test up -d postgres-test` "
    "(or point LUNABLUE_TEST_DATABASE_URL at a database)"
)


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
    """In-memory audit recorder for tests that don't need Postgres."""
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


# -- Postgres (audit) ----------------------------------------------------------


def _probe_database() -> str | None:
    """None when the test database answers, else the failure summary."""

    async def probe() -> None:
        engine = create_async_engine(TEST_DATABASE_URL)
        try:
            async with engine.connect():
                pass
        finally:
            await engine.dispose()

    try:
        asyncio.run(probe())
        return None
    except Exception as exc:  # noqa: BLE001 - any failure means "skip"
        return f"{type(exc).__name__}: {exc}"


@pytest.fixture(scope="session")
def migrated_database() -> str:
    """URL of the test database, migrated to Alembic head once per session."""
    failure = _probe_database()
    if failure is not None:
        message = f"{_POSTGRES_HINT}. Probe failed: {failure}"
        if os.environ.get("LUNABLUE_TEST_REQUIRE_DB"):
            # CI provisions Postgres and must never silently skip these tests.
            pytest.fail(message)
        pytest.skip(message)
    config = Config()
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    # migrations/env.py reads -x db_url=... ahead of application settings.
    config.cmd_opts = SimpleNamespace(x=[f"db_url={TEST_DATABASE_URL}"])
    command.upgrade(config, "head")
    return TEST_DATABASE_URL


@pytest.fixture
async def audit_db(migrated_database) -> str:
    """Bind the process-wide engine to the migrated test database for one
    test; the audit tables are truncated afterwards so state never leaks."""
    db.init_engine(migrated_database)
    try:
        yield migrated_database
    finally:
        try:
            async with db.session_scope() as session:
                await session.execute(
                    text(
                        "TRUNCATE agent_events, prompt_responses, "
                        "prompt_requests, sessions CASCADE"
                    )
                )
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
