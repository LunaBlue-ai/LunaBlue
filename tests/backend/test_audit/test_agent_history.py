"""Agent-history reconstruction from ``agent_events`` (Step 16).

The audit trail is the durable record of an agent's life: these tests write a
full lifecycle through the real :class:`AuditService` into the test database,
then read it back via :meth:`fetch_agent_events` and via the API detail
endpoint's evicted-agent path (``live=false``), which rebuilds every field
from the trail alone.
"""

import uuid

from httpx import ASGITransport, AsyncClient

from tests.backend.fakes import make_app, make_runtime


def _record_lifecycle(service, agent_id: str, *, request_id: str) -> None:
    """One complete audited lifecycle: spawned → running → progress → done."""
    # agent_events.request_id references prompt_requests: audit the prompt
    # that spawned the agent first, exactly as the real pipeline does.
    service.record_prompt_request(request_id, "prompt that spawned the agent")
    service.record_agent_event(
        agent_id,
        "spawned",
        request_id=request_id,
        state="pending",
        payload={
            "kind": "research",
            "task": "summarize the moons of Jupiter",
            "params": {"depth": 2},
            "session_id": "s-history",
        },
    )
    service.record_agent_event(
        agent_id, "state_change", request_id=request_id, state="running"
    )
    service.record_agent_event(
        agent_id,
        "progress",
        request_id=request_id,
        state="running",
        payload={"phase": "collecting", "fraction": 0.5},
    )
    service.record_agent_event(
        agent_id,
        "completed",
        request_id=request_id,
        state="completed",
        payload={"summary": "four large moons"},
    )


async def test_fetch_agent_events_returns_one_agents_trail_oldest_first(
    audit_service,
):
    agent_id = f"a-{uuid.uuid4().hex[:12]}"
    other_id = f"a-{uuid.uuid4().hex[:12]}"
    _record_lifecycle(audit_service, agent_id, request_id="r-history")
    audit_service.record_agent_event(other_id, "spawned", state="pending")
    await audit_service.flush()

    events = await audit_service.fetch_agent_events(agent_id)

    assert [e.event_type for e in events] == [
        "spawned",
        "state_change",
        "progress",
        "completed",
    ]
    assert all(e.agent_id == agent_id for e in events)  # no cross-agent bleed
    assert all(e.request_id == "r-history" for e in events)
    timestamps = [e.timestamp for e in events]
    assert timestamps == sorted(timestamps)
    assert events[0].payload["task"] == "summarize the moons of Jupiter"
    assert events[-1].state == "completed"


async def test_fetch_agent_events_limit_keeps_the_most_recent(audit_service):
    agent_id = f"a-{uuid.uuid4().hex[:12]}"
    _record_lifecycle(audit_service, agent_id, request_id="r-limit")
    await audit_service.flush()

    events = await audit_service.fetch_agent_events(agent_id, limit=2)

    # The most recent rows, still returned oldest first.
    assert [e.event_type for e in events] == ["progress", "completed"]


async def test_api_reconstructs_an_evicted_agent_from_the_audit_trail(
    tmp_path, audit_service
):
    """GET /api/agents/{id} for an agent absent from live state rebuilds the
    full detail (kind, task, params, progress, result) from agent_events."""
    agent_id = f"a-{uuid.uuid4().hex[:12]}"
    _record_lifecycle(audit_service, agent_id, request_id="r-evicted")
    await audit_service.flush()

    runtime, _ = make_runtime(tmp_path)
    # A fresh app whose state store has never seen this agent: exactly the
    # evicted case — only the audit record remains.
    app = make_app(audit_service, runtime)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        resp = await client.get(f"/api/agents/{agent_id}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["live"] is False
    assert body["agent_id"] == agent_id
    assert body["kind"] == "research"
    assert body["state"] == "completed"
    assert body["session_id"] == "s-history"
    assert body["request_id"] == "r-evicted"
    assert body["task"] == "summarize the moons of Jupiter"
    assert body["params"] == {"depth": 2}
    assert body["progress_phase"] == "collecting"
    assert body["progress_fraction"] == 1.0  # completed pins it to done
    assert body["last_result"] == "four large moons"
    assert body["error"] is None
    assert [e["event_type"] for e in body["events"]] == [
        "spawned",
        "state_change",
        "progress",
        "completed",
    ]
