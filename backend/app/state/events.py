"""Pub/sub bridge from state-store mutations to live subscribers (Step 13).

:class:`EventBus` is the only path from :mod:`app.state.store` to
``api/websocket.py`` (docs/Architecture.md): the lifespan attaches
:meth:`EventBus.publish` as the store's notify hook, so every mutation fans
out as a :class:`BusEvent` without the store (or orchestration) knowing
anything about WebSockets.

Delivery model: each subscriber gets its own bounded ``asyncio.Queue``.
Publishing never blocks and never fails a mutation — when a slow consumer's
queue is full, its oldest pending event is dropped with a logged warning.
Dropped events are safe to lose because every payload is a full post-mutation
snapshot, and the connect-time ``snapshot`` message (api/websocket.py) resyncs
clients from scratch.

Event types mirror :class:`~app.state.store.StoreEvent` kinds:

- ``run_updated`` — a run was created, changed phase, or reached a terminal
  state; payload is the run snapshot.
- ``run_evicted`` — a finished run rolled out of the retention window.
- ``session_updated`` — a session was created or touched.
- ``agent_updated`` — an agent changed (shape defined now, used in Step 14).

Every event carries a process-wide monotonic sequence number and a UTC
timestamp, so consumers can order events and discard ones already reflected
in a snapshot.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from app.state.store import (
    AgentSnapshot,
    RunSnapshot,
    SessionSnapshot,
    StoreEvent,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class BusEvent:
    """One published state change, stamped for ordering."""

    type: str  # a StoreEvent kind: run_updated, run_evicted, session_updated, agent_updated
    seq: int  # monotonically increasing per bus, starting at 1
    ts: datetime  # publication time (UTC)
    payload: RunSnapshot | SessionSnapshot | AgentSnapshot


class EventBus:
    """Fan-out of store events to per-subscriber bounded queues.

    Single-event-loop only (like the store itself): ``publish`` runs on the
    loop via the store's notify hook, so queue bookkeeping needs no locking.
    """

    def __init__(self, *, max_queue: int = 256) -> None:
        self._max_queue = max(1, max_queue)
        self._queues: set[asyncio.Queue[BusEvent]] = set()
        self._seq = 0

    @property
    def seq(self) -> int:
        """Sequence number of the most recently published event (0 if none)."""
        return self._seq

    @property
    def subscriber_count(self) -> int:
        return len(self._queues)

    def publish(self, event: StoreEvent) -> None:
        """Stamp one store event and fan it out to every subscriber.

        Matches :data:`~app.state.store.StoreNotifyHook`, so the lifespan
        attaches this method directly via ``store.set_notify(bus.publish)``.
        Never blocks: a full subscriber queue drops its oldest event instead.
        """
        self._seq += 1
        bus_event = BusEvent(
            type=event.kind,
            seq=self._seq,
            ts=datetime.now(timezone.utc),
            payload=event.snapshot,
        )
        for queue in self._queues:
            try:
                queue.put_nowait(bus_event)
            except asyncio.QueueFull:
                dropped = queue.get_nowait()
                logger.warning(
                    "Slow event subscriber: dropped %s (seq=%d) to enqueue seq=%d",
                    dropped.type,
                    dropped.seq,
                    bus_event.seq,
                )
                queue.put_nowait(bus_event)

    def subscribe(self) -> "Subscription":
        """Register a new subscriber and return its event stream.

        The subscriber's queue is registered *before* this returns, so a
        caller can take a store snapshot immediately afterwards and know that
        every later mutation is either in the snapshot or in the stream
        (compare ``BusEvent.seq`` against :attr:`seq` at snapshot time to
        drop the overlap). Callers must release the subscription with
        :meth:`Subscription.aclose` (e.g. via ``contextlib.aclosing``).
        """
        queue: asyncio.Queue[BusEvent] = asyncio.Queue(self._max_queue)
        self._queues.add(queue)
        return Subscription(self._queues, queue)


class Subscription:
    """One subscriber's async-iterator view of the bus.

    A plain class rather than an async generator so that ``aclose`` always
    unsubscribes, even if iteration never started or was cancelled mid-wait.
    """

    def __init__(
        self,
        registry: set["asyncio.Queue[BusEvent]"],
        queue: "asyncio.Queue[BusEvent]",
    ) -> None:
        self._registry = registry
        self._queue = queue
        self._closed = False

    def __aiter__(self) -> "Subscription":
        return self

    async def __anext__(self) -> BusEvent:
        if self._closed:
            raise StopAsyncIteration
        return await self._queue.get()

    async def aclose(self) -> None:
        """Unsubscribe: idempotent, safe at any point of the iteration."""
        self._closed = True
        self._registry.discard(self._queue)
