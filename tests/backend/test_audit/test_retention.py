"""Tests for the audit retention policy (Step 17, ``app/audit/retention.py``).

These run against the suite's temp-file SQLite database via ``audit_db``
(always available
with instructions when unreachable): rows are seeded on both sides of the
window and only the old ones may go.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.audit import db, models
from app.audit.retention import apply_retention, resolve_windows

NOW = datetime(2026, 7, 15, 12, 0, 0, tzinfo=timezone.utc)


def days_ago(days: int) -> datetime:
    return NOW - timedelta(days=days)


@pytest.fixture
async def seeded(audit_db):
    """Two sessions/requests/responses/agent events: one 100 days old, one
    fresh (1 day). Returns the (old, new) request ids."""
    suffix = uuid.uuid4().hex[:8]
    old_id, new_id = f"r-old-{suffix}", f"r-new-{suffix}"
    async with db.session_scope() as session:
        for request_id, age in ((old_id, 100), (new_id, 1)):
            session.add(
                models.Session(
                    session_id=f"s-{request_id}",
                    created_at=days_ago(age),
                    updated_at=days_ago(age),
                )
            )
            # No ORM relationships are defined, so flush explicitly to keep
            # the FK parents ahead of their children.
            await session.flush()
            session.add(
                models.PromptRequest(
                    request_id=request_id,
                    session_id=f"s-{request_id}",
                    timestamp=days_ago(age),
                    raw_prompt=f"prompt aged {age}d",
                )
            )
            await session.flush()
            session.add(
                models.PromptResponse(
                    request_id=request_id,
                    timestamp=days_ago(age),
                    final_output="output",
                )
            )
            session.add(
                models.AgentEvent(
                    agent_id=f"a-{request_id}",
                    request_id=request_id,
                    timestamp=days_ago(age),
                    event_type="spawned",
                )
            )
            await session.flush()
    return old_id, new_id


async def _count(model) -> int:
    async with db.session_scope() as session:
        return (
            await session.execute(select(func.count()).select_from(model))
        ).scalar_one()


async def test_dry_run_reports_counts_without_deleting(seeded):
    windows = resolve_windows(30, {})
    affected = await apply_retention(windows=windows, now=NOW, dry_run=True)
    assert affected == {
        "prompt_responses": 1,
        "agent_events": 1,
        "prompt_requests": 1,
        "sessions": 1,
    }
    # Nothing was touched.
    assert await _count(models.PromptRequest) == 2
    assert await _count(models.PromptResponse) == 2
    assert await _count(models.AgentEvent) == 2
    assert await _count(models.Session) == 2


async def test_retention_deletes_only_rows_older_than_the_window(seeded):
    old_id, new_id = seeded
    affected = await apply_retention(windows=resolve_windows(30, {}), now=NOW)
    assert affected == {
        "prompt_responses": 1,
        "agent_events": 1,
        "prompt_requests": 1,
        "sessions": 1,
    }
    async with db.session_scope() as session:
        assert await session.get(models.PromptRequest, old_id) is None
        fresh = await session.get(models.PromptRequest, new_id)
        assert fresh is not None
        assert fresh.raw_prompt == "prompt aged 1d"
    assert await _count(models.PromptResponse) == 1
    assert await _count(models.AgentEvent) == 1
    assert await _count(models.Session) == 1

    # Idempotent: a second run finds nothing left to delete.
    again = await apply_retention(windows=resolve_windows(30, {}), now=NOW)
    assert all(count == 0 for count in again.values())


async def test_zero_window_keeps_rows_forever(seeded):
    affected = await apply_retention(windows=resolve_windows(0, {}), now=NOW)
    assert all(count == 0 for count in affected.values())
    assert await _count(models.PromptRequest) == 2


async def test_per_table_override_narrows_one_table(seeded):
    # Default keeps everything (0), but agent_events get a 30-day window.
    windows = resolve_windows(0, {"agent_events": 30})
    affected = await apply_retention(windows=windows, now=NOW)
    assert affected["agent_events"] == 1
    assert affected["prompt_requests"] == 0
    assert await _count(models.AgentEvent) == 1
    assert await _count(models.PromptRequest) == 2
