"""Structured audit writer, decoupled from the request path.

Callers (routes, graph nodes) emit typed events through the ``record_*``
methods, which enqueue onto a bounded in-memory queue and return immediately —
no DB round-trip ever happens on the caller's path. A single background
consumer task (started/stopped by the ``main.py`` lifespan handler) drains the
queue and writes batches to Postgres using its own sessions.

Failure policy:

- A failed write is logged at ERROR with the event payload and the consumer
  keeps going; nothing ever raises back into the request path.
- A failed batch is retried event-by-event so one bad row cannot take down
  the rest of the batch.
- Overflow policy: the queue is bounded (``AuditService(max_queue_size=...)``).
  When full, the *oldest* queued event is dropped to make room for the
  incoming one — under sustained backpressure the most recent events are the
  ones worth keeping for live debugging. Sustained overflow (e.g. a long
  Postgres outage) is reported as one aggregate ERROR per
  ``drop_log_interval`` seconds rather than per-event spam (Step 17); every
  individual drop is still visible at DEBUG, and readiness surfaces the
  saturation via :attr:`AuditService.saturated`.

Redaction (Step 17): when a :class:`~app.audit.redaction.Redactor` is
attached, prompt and output text fields are masked on the producer side —
before the event is even enqueued — so unredacted text never sits in the
queue or reaches Postgres.
"""

import asyncio
import dataclasses
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from fastapi import Request
from sqlalchemy import insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.audit import db, models
from app.audit.redaction import Redactor

logger = logging.getLogger(__name__)

_DEFAULT_MAX_QUEUE_SIZE = 1000
_BATCH_MAX = 100
_DEFAULT_DROP_LOG_INTERVAL = 30.0

# Sentinel telling the consumer to exit once everything ahead of it is drained.
_STOP = object()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class SessionEvent:
    """A session was created or touched; upserted into ``sessions``."""

    session_id: str
    user_id: str | None = None
    metadata: dict[str, Any] | None = None
    timestamp: datetime = field(default_factory=_utcnow)


@dataclass(frozen=True, slots=True)
class PromptRequestEvent:
    """An inbound prompt: raw text, reviewed form, governance metadata."""

    request_id: str
    raw_prompt: str
    session_id: str | None = None
    user_id: str | None = None
    reviewed_prompt: str | None = None
    prompt_version: str | None = None
    governance: dict[str, Any] | None = None
    timestamp: datetime = field(default_factory=_utcnow)


@dataclass(frozen=True, slots=True)
class PromptResponseEvent:
    """LLM output and final assistant output for a request."""

    request_id: str
    llm_output: str | None = None
    final_output: str | None = None
    model_id: str | None = None
    usage: dict[str, Any] | None = None
    timestamp: datetime = field(default_factory=_utcnow)


@dataclass(frozen=True, slots=True)
class AgentEvent:
    """An agent lifecycle event or state transition."""

    agent_id: str
    event_type: str
    request_id: str | None = None
    state: str | None = None
    payload: dict[str, Any] | None = None
    timestamp: datetime = field(default_factory=_utcnow)


AuditEvent = SessionEvent | PromptRequestEvent | PromptResponseEvent | AgentEvent


class AuditService:
    """Queue-backed audit writer.

    Lifecycle: construct, :meth:`start` the consumer, emit events via the
    ``record_*`` methods, :meth:`close` on shutdown (drains the queue).
    """

    def __init__(
        self,
        max_queue_size: int = _DEFAULT_MAX_QUEUE_SIZE,
        *,
        redactor: Redactor | None = None,
        drop_log_interval: float = _DEFAULT_DROP_LOG_INTERVAL,
    ) -> None:
        self._queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=max_queue_size)
        self._consumer: asyncio.Task[None] | None = None
        self._closed = False
        self._redactor = redactor
        # Overflow accounting (Step 17): aggregate reporting plus the
        # counters readiness exposes.
        self._drop_log_interval = drop_log_interval
        self._dropped_total = 0
        self._dropped_since_log = 0
        self._last_drop_log = 0.0

    # -- introspection (readiness) --------------------------------------------

    @property
    def queue_depth(self) -> int:
        """Events currently waiting to be written."""
        return self._queue.qsize()

    @property
    def queue_capacity(self) -> int:
        return self._queue.maxsize

    @property
    def dropped_total(self) -> int:
        """Events dropped to overflow since the process started."""
        return self._dropped_total

    @property
    def saturated(self) -> bool:
        """True while the queue is full — the next event will drop the
        oldest. Readiness reports this as an unhealthy audit pipeline."""
        return self._queue.full()

    def _redact(self, text: str | None) -> str | None:
        return text if self._redactor is None else self._redactor.redact(text)

    # -- producer side (hot path) -------------------------------------------

    def record_session(
        self,
        session_id: str,
        *,
        user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._enqueue(
            SessionEvent(session_id=session_id, user_id=user_id, metadata=metadata)
        )

    def record_prompt_request(
        self,
        request_id: str,
        raw_prompt: str,
        *,
        session_id: str | None = None,
        user_id: str | None = None,
        reviewed_prompt: str | None = None,
        prompt_version: str | None = None,
        governance: dict[str, Any] | None = None,
    ) -> None:
        self._enqueue(
            PromptRequestEvent(
                request_id=request_id,
                # With redaction enabled the *redacted* text is what the
                # raw_prompt column stores (see docs/DataRetention.md for
                # the trade-off).
                raw_prompt=self._redact(raw_prompt),
                session_id=session_id,
                user_id=user_id,
                reviewed_prompt=self._redact(reviewed_prompt),
                prompt_version=prompt_version,
                governance=governance,
            )
        )

    def record_prompt_response(
        self,
        request_id: str,
        *,
        llm_output: str | None = None,
        final_output: str | None = None,
        model_id: str | None = None,
        usage: dict[str, Any] | None = None,
    ) -> None:
        self._enqueue(
            PromptResponseEvent(
                request_id=request_id,
                llm_output=self._redact(llm_output),
                final_output=self._redact(final_output),
                model_id=model_id,
                usage=usage,
            )
        )

    def record_agent_event(
        self,
        agent_id: str,
        event_type: str,
        *,
        request_id: str | None = None,
        state: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self._enqueue(
            AgentEvent(
                agent_id=agent_id,
                event_type=event_type,
                request_id=request_id,
                state=state,
                payload=payload,
            )
        )

    # -- reads (Step 15: the agent detail API) --------------------------------

    async def fetch_agent_events(
        self, agent_id: str, *, limit: int = 200
    ) -> list[AgentEvent]:
        """The most recent ``agent_events`` rows for one agent, oldest first.

        Reads go straight to Postgres and deliberately do not wait for the
        write queue to drain: a just-emitted event may lag by one consumer
        batch, which is acceptable for status views and keeps this read path
        immune to write-side backpressure.
        """
        stmt = (
            select(models.AgentEvent)
            .where(models.AgentEvent.agent_id == agent_id)
            .order_by(
                models.AgentEvent.timestamp.desc(), models.AgentEvent.id.desc()
            )
            .limit(limit)
        )
        async with db.session_scope() as session:
            rows = list((await session.execute(stmt)).scalars())
        return [
            AgentEvent(
                agent_id=row.agent_id,
                event_type=row.event_type,
                request_id=row.request_id,
                state=row.state,
                payload=row.payload,
                timestamp=row.timestamp,
            )
            for row in reversed(rows)
        ]

    def _enqueue(self, event: AuditEvent) -> None:
        """Queue an event without blocking; never raises to the caller."""
        if self._closed:
            logger.error("Audit event after shutdown, dropped: %r", event)
            return
        while True:
            try:
                self._queue.put_nowait(event)
                return
            except asyncio.QueueFull:
                # Overflow policy: drop the oldest queued event (see module
                # docstring) and retry.
                try:
                    dropped = self._queue.get_nowait()
                    self._queue.task_done()
                except asyncio.QueueEmpty:  # pragma: no cover - racy edge
                    continue
                self._note_drop(dropped)

    def _note_drop(self, dropped: AuditEvent) -> None:
        """Account for one overflow drop; report in aggregate (Step 17).

        Under a sustained Postgres outage the queue overflows on every event;
        one ERROR per ``drop_log_interval`` summarizing the count replaces
        the per-event spam, while DEBUG keeps the individual payloads.
        """
        self._dropped_total += 1
        self._dropped_since_log += 1
        logger.debug("Audit queue full, dropped oldest event: %r", dropped)
        now = time.monotonic()
        if (
            self._last_drop_log
            and now - self._last_drop_log < self._drop_log_interval
        ):
            return
        logger.error(
            "Audit queue full: dropped %d event(s) in the last interval "
            "(%d total since start); most recent drop: %s",
            self._dropped_since_log,
            self._dropped_total,
            type(dropped).__name__,
        )
        self._dropped_since_log = 0
        self._last_drop_log = now

    # -- lifecycle -----------------------------------------------------------

    def start(self) -> None:
        """Start the background consumer; called from lifespan startup."""
        if self._consumer is None:
            self._consumer = asyncio.create_task(
                self._consume(), name="audit-consumer"
            )

    async def close(self, timeout: float = 10.0) -> None:
        """Stop accepting events, drain the queue, and stop the consumer.

        Events enqueued before ``close`` sit ahead of the stop sentinel and
        are written (or logged as failed) before the consumer exits. If the
        drain exceeds ``timeout`` (e.g. Postgres is hanging), the consumer is
        cancelled and remaining events are lost with an error log.
        """
        if self._closed:
            return
        self._closed = True
        if self._consumer is None:
            return
        while True:
            try:
                self._queue.put_nowait(_STOP)
                break
            except asyncio.QueueFull:
                dropped = self._queue.get_nowait()
                self._queue.task_done()
                logger.error("Audit queue full at shutdown, dropped: %r", dropped)
        try:
            await asyncio.wait_for(self._consumer, timeout)
        except asyncio.TimeoutError:
            logger.error(
                "Audit drain timed out after %.1fs; %d events lost",
                timeout,
                self._queue.qsize(),
            )
        self._consumer = None

    async def flush(self) -> None:
        """Wait until every event enqueued so far has been processed."""
        await self._queue.join()

    # -- consumer side -------------------------------------------------------

    async def _consume(self) -> None:
        while True:
            event = await self._queue.get()
            batch: list[AuditEvent] = []
            stop = event is _STOP
            if not stop:
                batch.append(event)
                # Drain whatever else is already queued (bounded) into one
                # transaction; stop early if the shutdown sentinel appears.
                while len(batch) < _BATCH_MAX:
                    try:
                        nxt = self._queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    if nxt is _STOP:
                        stop = True
                        break
                    batch.append(nxt)
            if batch:
                await self._write_batch(batch)
            for _ in range(len(batch) + (1 if stop else 0)):
                self._queue.task_done()
            if stop:
                return

    async def _write_batch(self, batch: list[AuditEvent]) -> None:
        try:
            async with db.session_scope() as session:
                for event in batch:
                    await session.execute(self._statement(event))
        except Exception:
            if len(batch) == 1:
                logger.error(
                    "Audit write failed, event lost: %r",
                    dataclasses.asdict(batch[0]),
                    exc_info=True,
                )
                return
            # Retry individually so one bad event can't sink the batch.
            for event in batch:
                await self._write_batch([event])

    @staticmethod
    def _statement(event: AuditEvent):
        """Map a typed event to its INSERT statement."""
        match event:
            case SessionEvent():
                # The mapped attribute is ``meta``: ``metadata`` would resolve
                # to the declarative class's MetaData, not the column.
                stmt = pg_insert(models.Session).values(
                    session_id=event.session_id,
                    user_id=event.user_id,
                    created_at=event.timestamp,
                    updated_at=event.timestamp,
                    meta=event.metadata,
                )
                # Re-emitting a session updates it instead of erroring; only
                # overwrite fields the event actually carries.
                update: dict[str, Any] = {"updated_at": event.timestamp}
                if event.user_id is not None:
                    update["user_id"] = stmt.excluded.user_id
                if event.metadata is not None:
                    update["metadata"] = stmt.excluded["metadata"]
                return stmt.on_conflict_do_update(
                    index_elements=[models.Session.session_id], set_=update
                )
            case PromptRequestEvent():
                return insert(models.PromptRequest).values(
                    request_id=event.request_id,
                    session_id=event.session_id,
                    timestamp=event.timestamp,
                    user_id=event.user_id,
                    raw_prompt=event.raw_prompt,
                    reviewed_prompt=event.reviewed_prompt,
                    prompt_version=event.prompt_version,
                    governance=event.governance,
                )
            case PromptResponseEvent():
                return insert(models.PromptResponse).values(
                    request_id=event.request_id,
                    timestamp=event.timestamp,
                    llm_output=event.llm_output,
                    final_output=event.final_output,
                    model_id=event.model_id,
                    usage=event.usage,
                )
            case AgentEvent():
                return insert(models.AgentEvent).values(
                    agent_id=event.agent_id,
                    request_id=event.request_id,
                    timestamp=event.timestamp,
                    event_type=event.event_type,
                    state=event.state,
                    payload=event.payload,
                )
            case _:  # pragma: no cover - guarded by AuditEvent typing
                raise TypeError(f"Unknown audit event type: {type(event)!r}")


def get_audit_service(request: Request) -> AuditService:
    """FastAPI dependency: the process-wide service built in the lifespan."""
    return request.app.state.audit_service
