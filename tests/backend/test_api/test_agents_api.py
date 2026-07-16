"""Tests for the agent status endpoints (Step 15).

The app is wired with fakes (no Postgres, no model file); the state store and
the AgentRunner are real, so these tests cover the full spawn → live status →
settle → evict → audit-reconstruction loop the UI depends on.
"""

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from app.orchestration.agents.base import (
    AgentContext,
    AgentResult,
    AgentSpec,
    BackgroundAgent,
)
from app.orchestration.runner import AgentRunner
from app.state.store import StateStore
from tests.backend.fakes import FakeAuditService, make_app, make_runtime


async def wait_until(predicate, timeout: float = 2.0) -> None:
    """Poll until ``predicate()`` is true (background work has no handle to
    await, by design — spawning is fire-and-forget)."""
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.005)


def scripted(kind: str, run_fn) -> type[BackgroundAgent]:
    """An agent class whose ``run`` delegates to ``run_fn(context)``."""

    class _Scripted(BackgroundAgent):
        async def run(self, context: AgentContext) -> AgentResult:
            return await run_fn(context)

    _Scripted.kind = kind
    return _Scripted


@pytest.fixture
def audit():
    return FakeAuditService()


@pytest.fixture
def runtime(tmp_path):
    return make_runtime(tmp_path)[0]


def make_harness(audit, runtime, *, store=None, run_fn=None, start=False):
    """A fake-wired app plus client, optionally with a scripted agent type
    installed on a started runner (the API cancel/detail paths exercise the
    real runner either way)."""
    if store is None:
        store = StateStore(max_finished_runs=64)
    app = make_app(audit, runtime, store=store)
    if run_fn is not None:
        runner = AgentRunner(
            runtime=runtime,
            store=store,
            audit=audit,
            agent_types={"scripted": scripted("scripted", run_fn)},
        )
        app.state.agent_runner = runner
    if start:
        app.state.agent_runner.start()
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    return app, client, store


async def register_agents(store: StateStore) -> None:
    """Three agents across two sessions and three lifecycle states."""
    await store.register_agent("a-1", kind="research", task="t1", session_id="s-1")
    await store.register_agent("a-2", kind="research", task="t2", session_id="s-2")
    await store.register_agent("a-3", kind="summary", task="t3", session_id="s-1")
    await store.update_agent("a-1", state="running", progress_phase="reading")
    await store.update_agent("a-2", state="running")
    await store.update_agent("a-2", state="completed", last_result="done")


# -- GET /api/agents ---------------------------------------------------------


async def test_list_is_empty_without_agents(audit, runtime):
    _, client, _ = make_harness(audit, runtime)
    async with client:
        resp = await client.get("/api/agents")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_list_returns_agents_newest_first(audit, runtime):
    _, client, store = make_harness(audit, runtime)
    await register_agents(store)
    async with client:
        body = (await client.get("/api/agents")).json()
    assert [a["agent_id"] for a in body] == ["a-3", "a-2", "a-1"]
    by_id = {a["agent_id"]: a for a in body}
    assert by_id["a-1"]["state"] == "running"
    assert by_id["a-1"]["progress_phase"] == "reading"
    assert by_id["a-2"]["state"] == "completed"
    assert by_id["a-2"]["last_result"] == "done"
    assert by_id["a-3"]["state"] == "pending"
    # Summaries never carry the queued-task list (that is WS/detail material).
    assert "queued_tasks" not in body[0]


async def test_list_filters_by_state_and_session(audit, runtime):
    _, client, store = make_harness(audit, runtime)
    await register_agents(store)
    async with client:
        running = (await client.get("/api/agents", params={"state": "running"})).json()
        session1 = (
            await client.get("/api/agents", params={"session_id": "s-1"})
        ).json()
        both = (
            await client.get(
                "/api/agents", params={"state": "running", "session_id": "s-1"}
            )
        ).json()
        limited = (await client.get("/api/agents", params={"limit": 1})).json()
        bogus = await client.get("/api/agents", params={"state": "bogus"})
    assert [a["agent_id"] for a in running] == ["a-1"]
    assert [a["agent_id"] for a in session1] == ["a-3", "a-1"]
    assert [a["agent_id"] for a in both] == ["a-1"]
    assert [a["agent_id"] for a in limited] == ["a-3"]
    assert bogus.status_code == 422  # unknown states are rejected, not empty


# -- GET /api/agents/{agent_id} -----------------------------------------------


async def test_live_detail_includes_task_params_and_events(audit, runtime):
    app, client, store = make_harness(audit, runtime)
    # Spawn (workers not started): the agent stays pending, fully audited.
    spec = AgentSpec(
        kind="research",
        task="find sources",
        request_id="req-9",
        session_id="s-9",
        params={"depth": 2},
    )
    await app.state.agent_runner.spawn(spec)

    async with client:
        resp = await client.get(f"/api/agents/{spec.agent_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["live"] is True
    assert body["state"] == "pending"
    assert body["kind"] == "research"
    assert body["request_id"] == "req-9"
    assert body["session_id"] == "s-9"
    assert body["task"] == "find sources"
    assert body["params"] == {"depth": 2}
    assert [e["event_type"] for e in body["events"]] == ["spawned"]
    assert store.get_agent(spec.agent_id).state == "pending"


async def test_unknown_agent_returns_404(audit, runtime):
    _, client, _ = make_harness(audit, runtime)
    async with client:
        resp = await client.get("/api/agents/no-such-agent")
    assert resp.status_code == 404
    assert "audit" in resp.json()["detail"]


async def test_evicted_agent_detail_is_reconstructed_from_audit(audit, runtime):
    async def work(context: AgentContext) -> AgentResult:
        await context.report_progress("searching", fraction=0.5)
        return AgentResult(summary="found 3 links", payload={"links": 3})

    # Zero retention: settled agents are evicted immediately.
    app, client, store = make_harness(
        audit,
        runtime,
        store=StateStore(max_finished_agents=0),
        run_fn=work,
        start=True,
    )
    spec = AgentSpec(
        kind="scripted", task="hunt links", request_id="req-1", session_id="s-1",
        params={"depth": 1},
    )
    await _spawn_and_wait_evicted(app, store, spec)

    async with client:
        resp = await client.get(f"/api/agents/{spec.agent_id}")
        listing = (await client.get("/api/agents")).json()
    assert resp.status_code == 200
    body = resp.json()
    assert body["live"] is False
    assert body["state"] == "completed"
    assert body["kind"] == "scripted"
    assert body["task"] == "hunt links"
    assert body["params"] == {"depth": 1}
    assert body["request_id"] == "req-1"
    assert body["session_id"] == "s-1"
    assert body["last_result"] == "found 3 links"
    assert body["progress_fraction"] == 1.0
    assert body["progress_phase"] == "searching"
    assert [e["event_type"] for e in body["events"]] == [
        "spawned",
        "started",
        "progress",
        "completed",
    ]
    # The evicted agent is gone from the live list but not from the detail.
    assert listing == []


async def _spawn_and_wait_evicted(app, store, spec):
    runner = app.state.agent_runner
    await runner.spawn(spec)
    assert store.get_agent(spec.agent_id) is not None  # pending, still live
    await wait_until(lambda: store.get_agent(spec.agent_id) is None)
    await runner.close()


async def test_failed_evicted_agent_reconstructs_the_error(audit, runtime):
    async def work(context: AgentContext) -> AgentResult:
        raise RuntimeError("boom")

    app, client, store = make_harness(
        audit,
        runtime,
        store=StateStore(max_finished_agents=0),
        run_fn=work,
        start=True,
    )
    spec = AgentSpec(kind="scripted", task="explode")
    await _spawn_and_wait_evicted(app, store, spec)

    async with client:
        body = (await client.get(f"/api/agents/{spec.agent_id}")).json()
    assert body["live"] is False
    assert body["state"] == "failed"
    assert body["error"] == "RuntimeError: boom"
    assert body["last_result"] is None


# -- POST /api/agents/{agent_id}/cancel ----------------------------------------


async def test_cancel_pending_agent_settles_it(audit, runtime):
    app, client, store = make_harness(audit, runtime)
    spec = AgentSpec(kind="research", task="never starts", request_id="req-2")
    await app.state.agent_runner.spawn(spec)

    async with client:
        resp = await client.post(f"/api/agents/{spec.agent_id}/cancel")
        again = await client.post(f"/api/agents/{spec.agent_id}/cancel")
        missing = await client.post("/api/agents/nope/cancel")
    assert resp.status_code == 202
    assert resp.json()["state"] == "cancelled"
    assert store.get_agent(spec.agent_id).state == "cancelled"
    # The audit trail closes out with the cancellation.
    assert [e["event_type"] for e in audit.events_for(spec.agent_id)] == [
        "spawned",
        "cancelled",
    ]
    # Already settled → 409; unknown → 404.
    assert again.status_code == 409
    assert missing.status_code == 404


async def test_cancel_running_agent_moves_it_to_cancelled(audit, runtime):
    release = asyncio.Event()

    async def work(context: AgentContext) -> AgentResult:
        await context.report_progress("stalling", fraction=0.1)
        await release.wait()
        return AgentResult(summary="never happens")

    app, client, store = make_harness(audit, runtime, run_fn=work, start=True)
    runner = app.state.agent_runner
    spec = AgentSpec(kind="scripted", task="long haul")
    await runner.spawn(spec)
    await wait_until(lambda: store.get_agent(spec.agent_id).state == "running")

    async with client:
        resp = await client.post(f"/api/agents/{spec.agent_id}/cancel")
    assert resp.status_code == 202
    # Cancellation is asynchronous: accepted now, settled when it unwinds.
    await wait_until(lambda: store.get_agent(spec.agent_id).state == "cancelled")
    assert [e["event_type"] for e in audit.events_for(spec.agent_id)] == [
        "spawned",
        "started",
        "progress",
        "cancelled",
    ]
    await runner.close()


# -- documentation --------------------------------------------------------------


async def test_openapi_documents_the_agent_endpoints(audit, runtime):
    _, client, _ = make_harness(audit, runtime)
    async with client:
        spec = (await client.get("/openapi.json")).json()
    list_op = spec["paths"]["/api/agents"]["get"]
    assert list_op["summary"]
    detail_op = spec["paths"]["/api/agents/{agent_id}"]["get"]
    assert detail_op["summary"]
    assert "404" in detail_op["responses"]
    cancel_op = spec["paths"]["/api/agents/{agent_id}/cancel"]["post"]
    assert cancel_op["summary"]
    assert "404" in cancel_op["responses"]
    assert "409" in cancel_op["responses"]
