"""Integration tests for the audit service.

These run against the docker-compose test Postgres via the ``audit_db``
fixture (skipped with instructions when it is unreachable): they emit one of
each event type and assert the rows land, and exercise the failure/overflow/
shutdown policies from ``service.py``.
"""

import asyncio
import logging
import uuid

import pytest
from sqlalchemy import select

from app.audit import db
from app.audit.models import AgentEvent, PromptRequest, PromptResponse, Session
from app.audit.service import AuditService


@pytest.fixture
async def broken_engine():
    """Engine pointing at a port nothing listens on: every write fails."""
    db.init_engine("postgresql+asyncpg://nobody:nothing@127.0.0.1:1/nowhere")
    yield
    await db.dispose_engine()


async def test_all_event_types_land_in_postgres(audit_db):
    ids = uuid.uuid4().hex[:12]
    session_id, request_id, agent_id = f"s-{ids}", f"r-{ids}", f"a-{ids}"

    service = AuditService()
    service.start()
    try:
        service.record_session(session_id, user_id="u-1", metadata={"src": "test"})
        service.record_prompt_request(
            request_id,
            "raw prompt",
            session_id=session_id,
            user_id="u-1",
            reviewed_prompt="reviewed prompt",
            prompt_version="v1",
            governance={"flags": ["ok"]},
        )
        service.record_prompt_response(
            request_id,
            llm_output="llm text",
            final_output="final text",
            model_id="test-model",
            usage={"tokens": 3},
        )
        service.record_agent_event(
            agent_id,
            "state_change",
            request_id=request_id,
            state="running",
            payload={"step": 1},
        )
        await service.flush()

        async with db.session_scope() as s:
            sess = await s.get(Session, session_id)
            assert sess is not None and sess.user_id == "u-1"
            assert sess.meta == {"src": "test"}

            req = await s.get(PromptRequest, request_id)
            assert req is not None
            assert req.raw_prompt == "raw prompt"
            assert req.reviewed_prompt == "reviewed prompt"
            assert req.prompt_version == "v1"
            assert req.governance == {"flags": ["ok"]}
            assert req.timestamp.tzinfo is not None

            resp = (
                await s.execute(
                    select(PromptResponse).where(
                        PromptResponse.request_id == request_id
                    )
                )
            ).scalar_one()
            assert resp.final_output == "final text"
            assert resp.usage == {"tokens": 3}

            evt = (
                await s.execute(
                    select(AgentEvent).where(AgentEvent.agent_id == agent_id)
                )
            ).scalar_one()
            assert evt.event_type == "state_change"
            assert evt.payload == {"step": 1}
    finally:
        await service.close()


async def test_session_reemit_upserts(audit_db):
    session_id = f"s-{uuid.uuid4().hex[:12]}"
    service = AuditService()
    service.start()
    try:
        service.record_session(session_id)
        service.record_session(session_id, user_id="u-2")
        await service.flush()
        async with db.session_scope() as s:
            sess = await s.get(Session, session_id)
            assert sess is not None and sess.user_id == "u-2"
    finally:
        await service.close()


async def test_close_drains_pending_events(audit_db):
    """Events emitted just before shutdown are persisted by close()."""
    request_id = f"r-{uuid.uuid4().hex[:12]}"
    service = AuditService()
    service.start()
    service.record_prompt_request(request_id, "emitted right before shutdown")
    await service.close()
    async with db.session_scope() as s:
        assert await s.get(PromptRequest, request_id) is not None


async def test_record_is_nonblocking_and_failures_stay_off_request_path(
    broken_engine, caplog
):
    """With Postgres unreachable, record_* still returns instantly and the
    consumer logs the failed write instead of raising."""
    service = AuditService()
    service.start()
    with caplog.at_level(logging.ERROR, logger="app.audit.service"):
        loop = asyncio.get_running_loop()
        start = loop.time()
        service.record_prompt_request("r-doomed", "this write will fail")
        assert loop.time() - start < 0.05  # enqueue only, no DB round-trip
        await service.flush()
        await service.close()
    assert any("Audit write failed" in r.message for r in caplog.records)
    assert any("r-doomed" in r.message for r in caplog.records)


async def test_overflow_drops_oldest_with_one_aggregate_warning(caplog):
    """When the bounded queue is full the oldest events are dropped, and
    sustained overflow logs ONE aggregate ERROR per interval (Step 17)
    instead of per-event spam; individual payloads remain at DEBUG."""
    service = AuditService(max_queue_size=2)  # consumer never started
    with caplog.at_level(logging.DEBUG, logger="app.audit.service"):
        service.record_agent_event("agent-1", "first")
        service.record_agent_event("agent-2", "second")
        for i in range(3, 8):  # five drops in one burst
            service.record_agent_event(f"agent-{i}", "more")
    errors = [
        r
        for r in caplog.records
        if r.levelno == logging.ERROR and "queue full" in r.message
    ]
    assert len(errors) == 1  # the first drop reports; the burst aggregates
    # Every individual drop stays visible at DEBUG.
    debugs = [
        r
        for r in caplog.records
        if r.levelno == logging.DEBUG and "dropped oldest" in r.message
    ]
    assert len(debugs) == 5
    assert any("agent-1" in r.message for r in debugs)

    # Introspection for readiness: totals and saturation are exposed.
    assert service.dropped_total == 5
    assert service.saturated
    assert service.queue_depth == service.queue_capacity == 2

    # Drop-oldest semantics: the two newest events survive.
    remaining = [service._queue.get_nowait().agent_id for _ in range(2)]
    assert remaining == ["agent-6", "agent-7"]
