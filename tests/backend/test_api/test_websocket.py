"""Tests for the /ws live-state endpoint (Step 13).

These use Starlette's sync TestClient as a context manager so HTTP requests
and WebSocket sessions share one event loop (required: the EventBus queues
are loop-bound). The real lifespan needs Postgres and a model file, so it is
replaced with a no-op — the fakes wiring in :func:`tests.backend.fakes.make_app`
already provides everything the routes read from ``app.state``.
"""

import time
from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.config import get_settings
from tests.backend.fakes import FakeAuditService, make_app, make_runtime

# The full happy-path run_updated phase progression, in order.
_RUN_PHASES = [
    "received",
    "governance",
    "engineering",
    "reviewing",
    "responding",
    "completed",
]


@asynccontextmanager
async def _noop_lifespan(app):
    yield


@pytest.fixture(autouse=True)
def ws_settings(monkeypatch):
    """Pin WS_ENABLED=true regardless of any local .env; restore after."""
    monkeypatch.setenv("WS_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client(tmp_path):
    runtime, _ = make_runtime(tmp_path)
    app = make_app(FakeAuditService(), runtime)
    app.router.lifespan_context = _noop_lifespan
    with TestClient(app) as test_client:
        yield test_client


def _run_events_until_terminal(ws) -> list[dict]:
    """Read messages until the run reaches a terminal phase."""
    messages = []
    while True:
        message = ws.receive_json()
        messages.append(message)
        if message["type"] == "run_updated" and message["payload"]["phase"] in (
            "completed",
            "failed",
        ):
            return messages


def test_connect_sends_an_empty_snapshot_first(client):
    with client.websocket_connect("/ws") as ws:
        message = ws.receive_json()
    assert message["type"] == "snapshot"
    assert message["seq"] == 0
    assert isinstance(message["ts"], str)
    assert message["payload"] == {"sessions": [], "runs": [], "agents": []}


def test_snapshot_carries_existing_sessions_and_runs(client):
    resp = client.post("/api/prompt", json={"text": "hello"})
    body = resp.json()

    with client.websocket_connect("/ws") as ws:
        snapshot = ws.receive_json()

    runs = snapshot["payload"]["runs"]
    assert [r["request_id"] for r in runs] == [body["request_id"]]
    assert runs[0]["phase"] == "completed"
    sessions = snapshot["payload"]["sessions"]
    assert [s["session_id"] for s in sessions] == [body["session_id"]]
    assert sessions[0]["run_ids"] == [body["request_id"]]
    # The snapshot seq reflects the events that already happened; anything
    # streamed later on this connection must be strictly newer.
    assert snapshot["seq"] > 0


def test_run_progress_streams_live_with_monotonic_seq(client):
    with client.websocket_connect("/ws") as ws:
        snapshot = ws.receive_json()
        resp = client.post("/api/prompt", json={"text": "hello"})
        request_id = resp.json()["request_id"]
        messages = _run_events_until_terminal(ws)

    assert all({"type", "seq", "ts", "payload"} <= set(m) for m in messages)

    run_events = [m for m in messages if m["type"] == "run_updated"]
    assert [m["payload"]["phase"] for m in run_events] == _RUN_PHASES
    assert all(m["payload"]["request_id"] == request_id for m in run_events)

    # The session upsert is streamed too.
    assert any(m["type"] == "session_updated" for m in messages)

    # Strictly increasing seq, all newer than the connect snapshot.
    seqs = [m["seq"] for m in messages]
    assert seqs == sorted(set(seqs))
    assert all(seq > snapshot["seq"] for seq in seqs)


def test_two_clients_both_receive_the_same_run(client):
    with client.websocket_connect("/ws") as ws_a, client.websocket_connect(
        "/ws"
    ) as ws_b:
        ws_a.receive_json()
        ws_b.receive_json()
        client.post("/api/prompt", json={"text": "hello"})
        for ws in (ws_a, ws_b):
            run_events = [
                m
                for m in _run_events_until_terminal(ws)
                if m["type"] == "run_updated"
            ]
            assert [m["payload"]["phase"] for m in run_events] == _RUN_PHASES


def test_inbound_frames_are_ignored(client):
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_text('{"type": "not business data"}')
        client.post("/api/prompt", json={"text": "hello"})
        # The connection is still alive and streaming.
        assert _run_events_until_terminal(ws)


def test_disconnect_unsubscribes_from_the_bus(client):
    bus = client.app.state.event_bus
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        assert bus.subscriber_count == 1
    # The handler tears down asynchronously after the disconnect frame.
    deadline = time.monotonic() + 2.0
    while bus.subscriber_count and time.monotonic() < deadline:
        time.sleep(0.02)
    assert bus.subscriber_count == 0


def test_ws_disabled_rejects_the_handshake(client, monkeypatch):
    monkeypatch.setenv("WS_ENABLED", "false")
    get_settings.cache_clear()
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws"):
            pass  # pragma: no cover - never accepted


def test_plain_http_request_to_ws_stays_a_json_404(client):
    resp = client.get("/ws")
    assert resp.status_code == 404
