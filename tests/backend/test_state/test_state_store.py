"""Tests for the in-memory shared state store (Step 10)."""

import asyncio
import dataclasses

import pytest

from app.state.store import StateStore, StoreEvent


@pytest.fixture
def store():
    return StateStore(max_finished_runs=8)


# -- runs ------------------------------------------------------------------------


async def test_start_run_creates_received_run_and_session(store):
    snapshot = await store.start_run("req-1", "sess-1", user_id="u-1")

    assert snapshot.request_id == "req-1"
    assert snapshot.session_id == "sess-1"
    assert snapshot.phase == "received"
    assert snapshot.current_node is None
    assert snapshot.result_summary is None
    assert snapshot.error is None
    assert snapshot.created_at.tzinfo is not None
    [received] = snapshot.phases
    assert received.phase == "received"
    assert received.duration_ms is None  # still the current phase

    session = store.get_session("sess-1")
    assert session.user_id == "u-1"
    assert session.run_ids == ("req-1",)
    assert session.created_at.tzinfo is not None


async def test_duplicate_start_run_raises(store):
    await store.start_run("req-1", "sess-1")
    with pytest.raises(ValueError, match="already exists"):
        await store.start_run("req-1", "sess-2")


async def test_phase_updates_record_timed_history(store):
    await store.start_run("req-1", "sess-1")
    await store.update_run_phase("req-1", "governance")
    snapshot = await store.update_run_phase(
        "req-1", "engineering", node="prompt_engineering"
    )

    assert snapshot.phase == "engineering"
    assert snapshot.current_node == "prompt_engineering"
    assert [p.phase for p in snapshot.phases] == [
        "received",
        "governance",
        "engineering",
    ]
    # Every left phase is closed out with a duration; the current one is open.
    assert all(p.duration_ms >= 0 for p in snapshot.phases[:-1])
    assert snapshot.phases[-1].duration_ms is None
    assert snapshot.updated_at >= snapshot.created_at


async def test_invalid_or_terminal_phase_via_update_raises(store):
    await store.start_run("req-1", "sess-1")
    with pytest.raises(ValueError):
        await store.update_run_phase("req-1", "daydreaming")
    with pytest.raises(ValueError, match="complete_run/fail_run"):
        await store.update_run_phase("req-1", "completed")


async def test_complete_run_is_terminal_with_summary(store):
    await store.start_run("req-1", "sess-1")
    await store.update_run_phase("req-1", "responding", node="respond")
    snapshot = await store.complete_run("req-1", result_summary="all good")

    assert snapshot.phase == "completed"
    assert snapshot.current_node is None
    assert snapshot.result_summary == "all good"
    assert snapshot.error is None
    # The terminal phase closes out the previous one's timing.
    assert snapshot.phases[-2].duration_ms >= 0


async def test_fail_run_carries_the_error_summary(store):
    await store.start_run("req-1", "sess-1")
    snapshot = await store.fail_run("req-1", "RuntimeError: kaboom")
    assert snapshot.phase == "failed"
    assert snapshot.error == "RuntimeError: kaboom"
    assert snapshot.result_summary is None


async def test_updates_after_terminal_are_ignored(store):
    """An abandoned (timed-out) graph run must not resurrect a failed run."""
    await store.start_run("req-1", "sess-1")
    await store.fail_run("req-1", "timed out")

    assert await store.update_run_phase("req-1", "responding") is None
    assert await store.complete_run("req-1", result_summary="late") is None
    assert await store.fail_run("req-1", "other") is None

    run = store.get_run("req-1")
    assert run.phase == "failed"
    assert run.error == "timed out"


async def test_updates_for_unknown_runs_are_ignored(store):
    assert await store.update_run_phase("nope", "governance") is None
    assert await store.complete_run("nope") is None
    assert await store.fail_run("nope", "boom") is None
    assert store.get_run("nope") is None


async def test_snapshots_are_frozen_and_detached(store):
    await store.start_run("req-1", "sess-1")
    before = store.get_run("req-1")

    with pytest.raises(dataclasses.FrozenInstanceError):
        before.phase = "completed"

    # A snapshot is a point-in-time copy: later mutations don't leak into it.
    await store.update_run_phase("req-1", "governance")
    assert before.phase == "received"
    assert len(before.phases) == 1

    session = store.get_session("sess-1")
    with pytest.raises(dataclasses.FrozenInstanceError):
        session.run_ids = ()


# -- retention -------------------------------------------------------------------


async def test_finished_runs_beyond_the_cap_are_evicted():
    store = StateStore(max_finished_runs=2)
    for i in range(1, 4):
        await store.start_run(f"req-{i}", "sess-1")
        await store.complete_run(f"req-{i}", result_summary=f"r{i}")

    assert store.get_run("req-1") is None  # oldest rolled off
    assert store.get_run("req-2") is not None
    assert store.get_run("req-3") is not None
    # The session's run list only references retained runs.
    assert store.get_session("sess-1").run_ids == ("req-3", "req-2")


async def test_in_flight_runs_are_never_evicted():
    store = StateStore(max_finished_runs=1)
    await store.start_run("req-live", "sess-1")
    await store.update_run_phase("req-live", "reviewing")
    for i in range(1, 4):
        await store.start_run(f"req-{i}", "sess-1")
        await store.complete_run(f"req-{i}")

    live = store.get_run("req-live")
    assert live is not None
    assert live.phase == "reviewing"


# -- sessions --------------------------------------------------------------------


async def test_touch_session_upserts_and_refreshes_activity(store):
    first = await store.touch_session("sess-1")
    assert first.user_id is None

    second = await store.touch_session("sess-1", user_id="u-9")
    assert second.user_id == "u-9"
    assert second.created_at == first.created_at
    assert second.last_activity_at >= first.last_activity_at

    # A later touch without user_id keeps the known user.
    third = await store.touch_session("sess-1")
    assert third.user_id == "u-9"


async def test_session_runs_newest_first_with_limit(store):
    for i in range(1, 5):
        await store.start_run(f"req-{i}", "sess-1")

    runs = store.session_runs("sess-1")
    assert [r.request_id for r in runs] == ["req-4", "req-3", "req-2", "req-1"]
    limited = store.session_runs("sess-1", limit=2)
    assert [r.request_id for r in limited] == ["req-4", "req-3"]
    assert store.session_runs("unknown") == ()


# -- concurrency -----------------------------------------------------------------


async def test_concurrent_runs_keep_independent_consistent_state(store):
    async def lifecycle(i: int):
        rid = f"req-{i}"
        await store.start_run(rid, f"sess-{i % 3}")
        await store.update_run_phase(rid, "governance")
        await store.update_run_phase(rid, "engineering", node="prompt_engineering")
        await store.update_run_phase(rid, "reviewing", node="llm_review")
        await store.update_run_phase(rid, "responding", node="respond")
        if i % 4 == 0:
            await store.fail_run(rid, f"boom {i}")
        else:
            await store.complete_run(rid, result_summary=f"done {i}")

    await asyncio.gather(*(lifecycle(i) for i in range(8)))

    for i in range(8):
        run = store.get_run(f"req-{i}")
        assert [p.phase for p in run.phases[:-1]] == [
            "received",
            "governance",
            "engineering",
            "reviewing",
            "responding",
        ]
        if i % 4 == 0:
            assert run.phase == "failed" and run.error == f"boom {i}"
        else:
            assert run.phase == "completed" and run.result_summary == f"done {i}"


# -- notify hook (Step 13 attaches here) -------------------------------------------


async def test_every_mutation_funnels_through_the_notify_hook(store):
    events: list[StoreEvent] = []
    store.set_notify(events.append)

    await store.start_run("req-1", "sess-1")
    await store.update_run_phase("req-1", "governance")
    await store.complete_run("req-1")
    await store.touch_session("sess-1")

    kinds = [e.kind for e in events]
    assert kinds == [
        "run_updated",  # started
        "session_updated",  # upserted by start_run
        "run_updated",  # phase change
        "run_updated",  # completed
        "session_updated",  # explicit touch
    ]
    # Payloads are post-mutation snapshots.
    assert events[0].snapshot.phase == "received"
    assert events[2].snapshot.phase == "governance"
    assert events[3].snapshot.phase == "completed"


async def test_eviction_is_notified(store):
    tight = StateStore(max_finished_runs=1)
    events: list[StoreEvent] = []
    tight.set_notify(events.append)

    for i in (1, 2):
        await tight.start_run(f"req-{i}", "sess-1")
        await tight.complete_run(f"req-{i}")

    evicted = [e for e in events if e.kind == "run_evicted"]
    assert [e.snapshot.request_id for e in evicted] == ["req-1"]


async def test_a_failing_hook_never_breaks_mutations(store):
    def bad_hook(event):
        raise RuntimeError("subscriber bug")

    store.set_notify(bad_hook)
    snapshot = await store.start_run("req-1", "sess-1")
    assert snapshot.phase == "received"
    assert store.get_run("req-1") is not None


# -- agents (structures only until Step 14) ----------------------------------------


async def test_agent_registry_starts_empty(store):
    assert store.list_agents() == ()


async def test_settled_agents_are_evicted_beyond_the_retention_window():
    tight = StateStore(max_finished_agents=1)
    events: list[StoreEvent] = []
    tight.set_notify(events.append)

    for i in (1, 2):
        await tight.register_agent(f"agent-{i}", kind="research", task=f"t{i}")
        await tight.update_agent(f"agent-{i}", state="running")
        await tight.update_agent(f"agent-{i}", state="completed", last_result="ok")

    # The oldest settled agent rolled out; the newest is retained.
    assert tight.get_agent("agent-1") is None
    assert [a.agent_id for a in tight.list_agents()] == ["agent-2"]
    evicted = [e for e in events if e.kind == "agent_evicted"]
    assert [e.snapshot.agent_id for e in evicted] == ["agent-1"]
    assert evicted[0].snapshot.state == "completed"


async def test_live_agents_are_never_evicted():
    tight = StateStore(max_finished_agents=0)
    await tight.register_agent("agent-1", kind="research", task="t1")
    await tight.register_agent("agent-2", kind="research", task="t2")
    await tight.update_agent("agent-2", state="running")

    # Pending/running agents stay despite the zero retention window ...
    assert {a.agent_id for a in tight.list_agents()} == {"agent-1", "agent-2"}
    # ... and leave immediately once settled.
    await tight.update_agent("agent-2", state="cancelled")
    assert tight.get_agent("agent-2") is None
