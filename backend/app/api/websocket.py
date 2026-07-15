"""The ``/ws`` endpoint: live state streaming to the frontend (Step 13).

Consumes the :class:`~app.state.events.EventBus` (the only bridge from the
state layer, per docs/Architecture.md) and pushes store changes to any number
of connected clients. Strictly one-way: events are notifications derived from
store snapshots — inbound frames are ignored, and no business data flows into
the backend over the socket.

Wire format
-----------
Every server → client message is a single JSON object::

    {"type": <str>, "seq": <int>, "ts": <ISO-8601 UTC>, "payload": <object>}

``seq`` is the bus's process-wide monotonic sequence number and ``ts`` the
publication timestamp. Message types:

- ``snapshot`` — sent exactly once, immediately after connect, so clients
  start consistent. ``payload`` is ``{"sessions": [SessionSummary],
  "runs": [RunStatus], "agents": [AgentStatus]}`` (schemas in
  ``api/schemas/state.py``). Its ``seq`` is the bus sequence at snapshot
  time; every following event on this connection has a strictly greater
  ``seq``, so clients need no deduplication.
- ``run_updated`` — a run was created, changed phase, or finished.
  ``payload`` is a full ``RunStatus`` (idempotent upsert on the client).
- ``run_evicted`` — a finished run left the live-state retention window;
  ``payload`` is its last ``RunStatus``.
- ``session_updated`` — a session was created or touched; ``payload`` is a
  ``SessionSummary``.
- ``agent_updated`` — an agent changed; ``payload`` is an ``AgentStatus``
  (shape defined now, populated in Step 14).

The frontend mirror of this contract lives in ``frontend/src/api/ws.ts``.

When ``settings.ws_enabled`` is false the handshake is rejected before being
accepted (the client sees the connection refused) and the UI degrades to
polling ``GET /api/runs/{id}``.
"""

import asyncio
import logging
from contextlib import aclosing
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel

from app.api.schemas.state import AgentStatus, RunStatus, SessionSummary
from app.config import get_settings
from app.state.events import BusEvent, EventBus, Subscription
from app.state.store import StateStore

logger = logging.getLogger(__name__)

router = APIRouter()

# Which schema serializes each event type's snapshot payload.
_PAYLOAD_SCHEMAS: dict[str, type[BaseModel]] = {
    "run_updated": RunStatus,
    "run_evicted": RunStatus,
    "session_updated": SessionSummary,
    "agent_updated": AgentStatus,
}


def _serialize_event(event: BusEvent) -> dict[str, Any] | None:
    """One bus event as a wire message; None for kinds with no wire mapping."""
    schema = _PAYLOAD_SCHEMAS.get(event.type)
    if schema is None:  # pragma: no cover - future store event kinds
        logger.warning("No wire mapping for event type %r; dropping", event.type)
        return None
    return {
        "type": event.type,
        "seq": event.seq,
        "ts": event.ts.isoformat(),
        "payload": schema.model_validate(event.payload).model_dump(mode="json"),
    }


def _snapshot_message(store: StateStore, seq: int) -> dict[str, Any]:
    """The connect-time full-state message (see module docstring)."""
    return {
        "type": "snapshot",
        "seq": seq,
        "ts": datetime.now(timezone.utc).isoformat(),
        "payload": {
            "sessions": [
                SessionSummary.model_validate(s).model_dump(mode="json")
                for s in store.list_sessions()
            ],
            "runs": [
                RunStatus.model_validate(r).model_dump(mode="json")
                for r in store.list_runs()
            ],
            "agents": [
                AgentStatus.model_validate(a).model_dump(mode="json")
                for a in store.list_agents()
            ],
        },
    }


async def _stream_events(
    websocket: WebSocket, subscription: Subscription, *, after_seq: int
) -> None:
    """Forward bus events to one client, skipping those the connect snapshot
    already covers (the subscription predates the snapshot, so the overlap is
    exactly ``seq <= after_seq``)."""
    async for event in subscription:
        if event.seq <= after_seq:
            continue
        message = _serialize_event(event)
        if message is not None:
            await websocket.send_json(message)


async def _receive_until_disconnect(websocket: WebSocket) -> None:
    """Drain (and ignore) inbound frames until the client goes away."""
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    if not get_settings().ws_enabled:
        # Reject the handshake outright; the UI falls back to polling.
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    store: StateStore = websocket.app.state.state_store
    bus: EventBus = websocket.app.state.event_bus

    await websocket.accept()
    # Subscribe before snapshotting: both happen synchronously on the event
    # loop, so every mutation is either in the snapshot or in the stream.
    async with aclosing(bus.subscribe()) as subscription:
        snapshot_seq = bus.seq
        try:
            await websocket.send_json(_snapshot_message(store, snapshot_seq))
        except (WebSocketDisconnect, RuntimeError):
            return  # client vanished during the handshake
        sender = asyncio.create_task(
            _stream_events(websocket, subscription, after_seq=snapshot_seq)
        )
        receiver = asyncio.create_task(_receive_until_disconnect(websocket))
        try:
            # Either the client disconnects (receiver returns / sender's send
            # raises) or the sender fails; the other task is then cancelled so
            # nothing leaks.
            await asyncio.wait(
                {sender, receiver}, return_when=asyncio.FIRST_COMPLETED
            )
        finally:
            for task in (sender, receiver):
                task.cancel()
            results = await asyncio.gather(sender, receiver, return_exceptions=True)
            for result in results:
                if isinstance(result, (WebSocketDisconnect, asyncio.CancelledError)):
                    continue
                if isinstance(result, BaseException):
                    logger.exception(
                        "WebSocket client task failed", exc_info=result
                    )
