"""The in-memory shared state store — the single source of truth for live
runtime state (Step 10).

:class:`StateStore` tracks active sessions, in-flight prompt runs, and (from
Step 14) background agents with their task queues. It is *live* state only:
completed and failed runs are retained for a bounded window and then evicted —
the Postgres audit chain is the durable record (docs/Architecture.md).

Concurrency model: mutations are async methods serialized by one
``asyncio.Lock``; every mutation body is fully synchronous once inside the
lock, so internal structures are never observable mid-update. Reads are plain
synchronous methods that build immutable snapshots without taking the lock —
under a single event loop they can never interleave with a mutation, which
keeps status polling free of contention with graph execution.

Layering: this module knows nothing about HTTP, WebSockets, or the audit
layer. Every mutation funnels through the single internal notify point
(:meth:`StateStore._emit`); Step 13's ``state/events.py`` attaches a hook via
:meth:`StateStore.set_notify` to broadcast changes without any store rewrite.
"""

import asyncio
import logging
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Every phase a prompt run moves through, in nominal order. The pipeline owns
# received/governance and the terminal transitions; the graph node wrappers
# (orchestration/graph.py) own engineering/reviewing/responding.
RUN_PHASES = (
    "received",
    "governance",
    "engineering",
    "reviewing",
    "responding",
    "completed",
    "failed",
)
TERMINAL_PHASES = frozenset({"completed", "failed"})
_INTERMEDIATE_PHASES = frozenset(RUN_PHASES) - TERMINAL_PHASES


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# -- immutable snapshots ---------------------------------------------------------
# Reads never hand out live internal references — only these frozen views.


@dataclass(frozen=True, slots=True)
class PhaseTransition:
    """One entry in a run's phase history."""

    phase: str
    node: str | None  # graph node that triggered the phase, if any
    entered_at: datetime
    duration_ms: float | None  # None while this is still the current phase


@dataclass(frozen=True, slots=True)
class RunSnapshot:
    """Point-in-time view of one prompt run."""

    request_id: str
    session_id: str
    phase: str
    current_node: str | None
    created_at: datetime
    updated_at: datetime
    result_summary: str | None  # short outcome summary once completed
    error: str | None  # failure summary once failed
    phases: tuple[PhaseTransition, ...]  # full timed history, oldest first


@dataclass(frozen=True, slots=True)
class SessionSnapshot:
    """Point-in-time view of one active session."""

    session_id: str
    user_id: str | None
    created_at: datetime
    last_activity_at: datetime
    run_ids: tuple[str, ...]  # retained runs only, newest first


@dataclass(frozen=True, slots=True)
class AgentTask:
    """One queued unit of background work (populated from Step 14)."""

    task_id: str
    description: str
    enqueued_at: datetime


@dataclass(frozen=True, slots=True)
class AgentSnapshot:
    """Point-in-time view of one background agent (populated from Step 14)."""

    agent_id: str
    session_id: str | None
    state: str
    created_at: datetime
    updated_at: datetime
    last_result: str | None
    queued_tasks: tuple[AgentTask, ...]


@dataclass(frozen=True, slots=True)
class StoreEvent:
    """What the notify hook receives on every mutation.

    ``kind`` is one of ``run_updated`` (created, phase change, or terminal),
    ``run_evicted``, ``session_updated``, or ``agent_updated`` (Step 14);
    ``snapshot`` is the post-mutation view of the affected entity.
    """

    kind: str
    snapshot: RunSnapshot | SessionSnapshot | AgentSnapshot


StoreNotifyHook = Callable[[StoreEvent], None]


# -- mutable internal records ----------------------------------------------------


@dataclass(slots=True)
class _PhaseEntry:
    phase: str
    node: str | None
    entered_at: datetime
    perf_started: float
    duration_ms: float | None = None


@dataclass(slots=True)
class _RunRecord:
    request_id: str
    session_id: str
    created_at: datetime
    updated_at: datetime
    result_summary: str | None = None
    error: str | None = None
    phases: list[_PhaseEntry] = field(default_factory=list)

    @property
    def phase(self) -> str:
        return self.phases[-1].phase

    @property
    def terminal(self) -> bool:
        return self.phase in TERMINAL_PHASES

    def enter_phase(self, phase: str, *, node: str | None, now: datetime) -> None:
        perf = time.perf_counter()
        if self.phases:
            last = self.phases[-1]
            last.duration_ms = (perf - last.perf_started) * 1000
        self.phases.append(
            _PhaseEntry(phase=phase, node=node, entered_at=now, perf_started=perf)
        )
        self.updated_at = now

    def snapshot(self) -> RunSnapshot:
        current = self.phases[-1]
        return RunSnapshot(
            request_id=self.request_id,
            session_id=self.session_id,
            phase=current.phase,
            current_node=current.node,
            created_at=self.created_at,
            updated_at=self.updated_at,
            result_summary=self.result_summary,
            error=self.error,
            phases=tuple(
                PhaseTransition(
                    phase=p.phase,
                    node=p.node,
                    entered_at=p.entered_at,
                    duration_ms=p.duration_ms,
                )
                for p in self.phases
            ),
        )


@dataclass(slots=True)
class _SessionRecord:
    session_id: str
    user_id: str | None
    created_at: datetime
    last_activity_at: datetime
    run_ids: list[str] = field(default_factory=list)  # oldest first

    def snapshot(self) -> SessionSnapshot:
        return SessionSnapshot(
            session_id=self.session_id,
            user_id=self.user_id,
            created_at=self.created_at,
            last_activity_at=self.last_activity_at,
            run_ids=tuple(reversed(self.run_ids)),
        )


@dataclass(slots=True)
class _AgentRecord:
    """Registry entry for one background agent. Step 14 populates these."""

    agent_id: str
    session_id: str | None
    state: str
    created_at: datetime
    updated_at: datetime
    last_result: str | None = None
    task_queue: deque[AgentTask] = field(default_factory=deque)

    def snapshot(self) -> AgentSnapshot:
        return AgentSnapshot(
            agent_id=self.agent_id,
            session_id=self.session_id,
            state=self.state,
            created_at=self.created_at,
            updated_at=self.updated_at,
            last_result=self.last_result,
            queued_tasks=tuple(self.task_queue),
        )


# -- the store -------------------------------------------------------------------


class StateStore:
    """Async-safe in-memory store for sessions, prompt runs, and agents."""

    def __init__(
        self,
        *,
        max_finished_runs: int = 256,
        notify: StoreNotifyHook | None = None,
    ) -> None:
        self._lock = asyncio.Lock()
        self._runs: dict[str, _RunRecord] = {}
        self._sessions: dict[str, _SessionRecord] = {}
        self._agents: dict[str, _AgentRecord] = {}
        # Terminal run ids in finish order; the eviction window rolls off the
        # left end once the cap is exceeded. In-flight runs are never evicted.
        self._finished: deque[str] = deque()
        self._max_finished_runs = max(0, max_finished_runs)
        self._notify_hook = notify

    # -- notify point (Step 13 attaches here) ------------------------------------

    def set_notify(self, hook: StoreNotifyHook | None) -> None:
        """Attach (or detach) the single change-notification hook."""
        self._notify_hook = hook

    def _emit(self, events: list[StoreEvent]) -> None:
        """The one internal notify point every mutation funnels through.

        Called after the lock is released so a hook can safely read back from
        the store. A misbehaving subscriber never breaks a mutation.
        """
        hook = self._notify_hook
        if hook is None:
            return
        for event in events:
            try:
                hook(event)
            except Exception:  # pragma: no cover - defensive
                logger.exception("State change hook failed for %s", event.kind)

    # -- mutations ----------------------------------------------------------------

    async def start_run(
        self, request_id: str, session_id: str, *, user_id: str | None = None
    ) -> RunSnapshot:
        """Register a new run in the ``received`` phase, upserting its session."""
        async with self._lock:
            if request_id in self._runs:
                raise ValueError(f"run {request_id!r} already exists")
            now = _utcnow()
            session = self._upsert_session(session_id, user_id=user_id, now=now)
            session.run_ids.append(request_id)
            record = _RunRecord(
                request_id=request_id,
                session_id=session_id,
                created_at=now,
                updated_at=now,
            )
            record.enter_phase("received", node=None, now=now)
            self._runs[request_id] = record
            snapshot = record.snapshot()
            events = [
                StoreEvent("run_updated", snapshot),
                StoreEvent("session_updated", session.snapshot()),
            ]
        self._emit(events)
        return snapshot

    async def update_run_phase(
        self, request_id: str, phase: str, *, node: str | None = None
    ) -> RunSnapshot | None:
        """Advance a run to an intermediate phase.

        Unknown, evicted, or already-terminal runs are ignored (returns
        ``None``): an abandoned graph run finishing after its request timed
        out must not resurrect a run the pipeline already failed.
        """
        if phase not in _INTERMEDIATE_PHASES:
            raise ValueError(
                f"invalid intermediate phase {phase!r}; terminal phases go "
                "through complete_run/fail_run"
            )
        async with self._lock:
            record = self._runs.get(request_id)
            if record is None or record.terminal:
                return None
            record.enter_phase(phase, node=node, now=_utcnow())
            snapshot = record.snapshot()
        self._emit([StoreEvent("run_updated", snapshot)])
        return snapshot

    async def complete_run(
        self, request_id: str, *, result_summary: str | None = None
    ) -> RunSnapshot | None:
        """Mark a run ``completed`` with a short result summary."""
        return await self._finish_run(
            request_id, "completed", result_summary=result_summary
        )

    async def fail_run(self, request_id: str, error: str) -> RunSnapshot | None:
        """Mark a run ``failed`` with the error summary."""
        return await self._finish_run(request_id, "failed", error=error)

    async def touch_session(
        self, session_id: str, *, user_id: str | None = None
    ) -> SessionSnapshot:
        """Upsert a session and refresh its last-activity timestamp."""
        async with self._lock:
            session = self._upsert_session(session_id, user_id=user_id, now=_utcnow())
            snapshot = session.snapshot()
        self._emit([StoreEvent("session_updated", snapshot)])
        return snapshot

    async def _finish_run(
        self,
        request_id: str,
        phase: str,
        *,
        result_summary: str | None = None,
        error: str | None = None,
    ) -> RunSnapshot | None:
        """Terminal transition plus retention: the first terminal state wins;
        the oldest finished runs beyond the cap are evicted."""
        async with self._lock:
            record = self._runs.get(request_id)
            if record is None or record.terminal:
                return None
            record.enter_phase(phase, node=None, now=_utcnow())
            record.result_summary = result_summary
            record.error = error
            snapshot = record.snapshot()
            events = [StoreEvent("run_updated", snapshot)]
            events.extend(self._evict_finished(request_id))
        self._emit(events)
        return snapshot

    def _evict_finished(self, request_id: str) -> list[StoreEvent]:
        """Roll the retention window forward. Caller holds the lock."""
        self._finished.append(request_id)
        events: list[StoreEvent] = []
        while len(self._finished) > self._max_finished_runs:
            victim_id = self._finished.popleft()
            victim = self._runs.pop(victim_id, None)
            if victim is None:  # pragma: no cover - defensive
                continue
            session = self._sessions.get(victim.session_id)
            if session is not None and victim_id in session.run_ids:
                session.run_ids.remove(victim_id)
            events.append(StoreEvent("run_evicted", victim.snapshot()))
        return events

    def _upsert_session(
        self, session_id: str, *, user_id: str | None = None, now: datetime
    ) -> _SessionRecord:
        """Create or touch a session record. Caller holds the lock."""
        session = self._sessions.get(session_id)
        if session is None:
            session = _SessionRecord(
                session_id=session_id,
                user_id=user_id,
                created_at=now,
                last_activity_at=now,
            )
            self._sessions[session_id] = session
        else:
            session.last_activity_at = now
            if user_id is not None:
                session.user_id = user_id
        return session

    # -- reads (immutable snapshots, lock-free) -----------------------------------

    def get_run(self, request_id: str) -> RunSnapshot | None:
        """Snapshot of one run, or ``None`` if unknown or evicted."""
        record = self._runs.get(request_id)
        return None if record is None else record.snapshot()

    def get_session(self, session_id: str) -> SessionSnapshot | None:
        """Snapshot of one session, or ``None`` if unknown."""
        session = self._sessions.get(session_id)
        return None if session is None else session.snapshot()

    def session_runs(
        self, session_id: str, *, limit: int = 20
    ) -> tuple[RunSnapshot, ...]:
        """Snapshots of a session's most recent retained runs, newest first."""
        session = self._sessions.get(session_id)
        if session is None:
            return ()
        recent = session.run_ids[-limit:] if limit > 0 else session.run_ids
        return tuple(
            self._runs[run_id].snapshot()
            for run_id in reversed(recent)
            if run_id in self._runs
        )

    def list_agents(self) -> tuple[AgentSnapshot, ...]:
        """Snapshots of all registered agents (empty until Step 14)."""
        return tuple(record.snapshot() for record in self._agents.values())
