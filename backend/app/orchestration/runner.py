"""Background execution of agent subgraphs (Step 14).

:class:`AgentRunner` owns an asyncio task queue: :meth:`AgentRunner.spawn`
registers an agent and enqueues it (fire-and-forget — the caller's response
never waits), and a configurable number of worker tasks (default 1) execute
agents one at a time each.

Every lifecycle transition and progress update is written to **both** sides:

- the :class:`~app.state.store.StateStore` agent registry, whose notify hook
  publishes ``agent_updated`` to live subscribers (Step 13), and
- the audit layer, as ``AgentEvent`` rows — an agent's full history is
  reconstructable from ``agent_events`` alone. Event types: ``spawned``,
  ``started``, ``progress``, ``completed``, ``failed``, ``cancelled``.

Failure isolation: an exception inside an agent marks that agent ``failed``
(with an error summary) and never disturbs the main service. Cancellation
(:meth:`AgentRunner.cancel`, or shutdown via :meth:`AgentRunner.close`)
settles the agent as ``cancelled`` and audits it as such.

Dependency rule (docs/Architecture.md): the runner injects the shared
:class:`~app.llm.runtime.LlamaRuntime`, store handles, and audit emitter into
each agent through its :class:`~app.orchestration.agents.base.AgentContext`;
state mutations go only through the store, audit only through
:class:`~app.audit.service.AuditService`.
"""

import asyncio
import logging
from typing import Any, Mapping

from app.audit.service import AuditService
from app.llm.runtime import LlamaRuntime
from app.orchestration.agents import BUILTIN_AGENT_TYPES
from app.orchestration.agents.base import (
    AgentContext,
    AgentResult,
    AgentSpec,
    BackgroundAgent,
)
from app.state.store import TERMINAL_AGENT_STATES, StateStore

logger = logging.getLogger(__name__)


class AgentRunner:
    """Owns the agent task queue and the workers that execute agent subgraphs.

    Lifecycle: construct, :meth:`start` the workers (lifespan startup),
    :meth:`spawn`/:meth:`cancel` while serving, :meth:`close` on shutdown
    (cancels pending and running agents gracefully, auditing each).
    """

    def __init__(
        self,
        *,
        runtime: LlamaRuntime,
        store: StateStore,
        audit: AuditService,
        workers: int = 1,
        agent_types: Mapping[str, type[BackgroundAgent]] | None = None,
    ) -> None:
        self._runtime = runtime
        self._store = store
        self._audit = audit
        self._worker_count = max(1, workers)
        self._agent_types = dict(
            BUILTIN_AGENT_TYPES if agent_types is None else agent_types
        )
        self._queue: asyncio.Queue[AgentSpec] = asyncio.Queue()
        self._workers: list[asyncio.Task[None]] = []
        # agent_id -> the task executing it, for targeted cancellation. An
        # entry exists exactly while its agent is being executed by a worker.
        self._running: dict[str, asyncio.Task[None]] = {}
        self._closed = False

    # -- public API ------------------------------------------------------------

    async def spawn(self, spec: AgentSpec) -> str:
        """Register ``spec`` as a pending agent and enqueue it; returns the
        agent id immediately (the work happens on a worker task)."""
        if self._closed:
            raise RuntimeError("AgentRunner is shut down")
        if spec.kind not in self._agent_types:
            raise ValueError(f"unknown agent kind {spec.kind!r}")
        await self._store.register_agent(
            spec.agent_id,
            kind=spec.kind,
            task=spec.task,
            session_id=spec.session_id,
            request_id=spec.request_id,
        )
        self._audit.record_agent_event(
            spec.agent_id,
            "spawned",
            request_id=spec.request_id,
            state="pending",
            payload={
                "kind": spec.kind,
                "task": spec.task,
                "session_id": spec.session_id,
                "params": dict(spec.params),
            },
        )
        self._queue.put_nowait(spec)
        return spec.agent_id

    async def cancel(self, agent_id: str) -> bool:
        """Cancel one agent. Running agents get their task cancelled (they
        settle as ``cancelled`` when it unwinds); pending ones are settled
        directly and skipped when a worker reaches them. Returns whether the
        agent was still cancellable (unknown or already-settled agents are
        not)."""
        snapshot = self._store.get_agent(agent_id)
        if snapshot is None or snapshot.state in TERMINAL_AGENT_STATES:
            return False
        task = self._running.get(agent_id)
        if task is not None:
            task.cancel()
            return True
        if snapshot.state != "pending":
            return False  # already unwinding; its own settle is in flight
        await self._settle(
            agent_id,
            "cancelled",
            request_id=snapshot.request_id,
            payload={"reason": "cancelled while pending"},
        )
        return True

    # -- lifecycle ---------------------------------------------------------------

    def start(self) -> None:
        """Start the worker tasks; called from lifespan startup."""
        if self._workers:
            return
        self._workers = [
            asyncio.create_task(self._worker(), name=f"agent-worker-{i}")
            for i in range(self._worker_count)
        ]

    async def close(self) -> None:
        """Graceful shutdown: refuse new spawns, cancel pending and running
        agents (auditing each as cancelled), then stop the workers.

        Runs before ``AuditService.close`` in the lifespan so every
        cancellation event still reaches Postgres.
        """
        if self._closed:
            return
        self._closed = True
        # Pending agents never reach a worker again; settle them now.
        while True:
            try:
                spec = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            await self._settle(
                spec.agent_id,
                "cancelled",
                request_id=spec.request_id,
                payload={"reason": "service shutdown before start"},
            )
            self._queue.task_done()
        # Running agents: cancel and wait for them to settle (each audits
        # its own cancellation on the way out).
        running = list(self._running.values())
        for task in running:
            task.cancel()
        if running:
            await asyncio.gather(*running, return_exceptions=True)
        for worker in self._workers:
            worker.cancel()
        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()

    # -- execution ----------------------------------------------------------------

    async def _worker(self) -> None:
        """One worker: executes queued agents sequentially, isolated from
        their outcomes — only worker cancellation (shutdown) stops the loop."""
        while True:
            spec = await self._queue.get()
            # No awaits between get() and registration: cancel() can never
            # observe an agent that is neither queued nor registered.
            task = asyncio.create_task(
                self._execute(spec), name=f"agent-{spec.agent_id}"
            )
            self._running[spec.agent_id] = task
            try:
                # wait() (not await task): an agent failure or cancellation
                # must not propagate into the worker loop.
                await asyncio.wait([task])
            finally:
                self._running.pop(spec.agent_id, None)
                self._queue.task_done()

    async def _execute(self, spec: AgentSpec) -> None:
        """Run one agent through its full lifecycle."""
        # The transition to running is the pickup gate: it returns None when
        # the agent was already cancelled while pending, and clears the
        # queued task entry otherwise.
        snapshot = await self._store.update_agent(spec.agent_id, state="running")
        if snapshot is None:
            return
        self._audit.record_agent_event(
            spec.agent_id, "started", request_id=spec.request_id, state="running"
        )
        agent = self._agent_types[spec.kind]()
        context = AgentContext(
            spec=spec,
            runtime=self._runtime,
            store=self._store,
            report_progress=self._progress_reporter(spec),
            emit_audit=self._audit_emitter(spec),
        )
        try:
            result = await agent.run(context)
        except asyncio.CancelledError:
            await asyncio.shield(
                self._settle(
                    spec.agent_id,
                    "cancelled",
                    request_id=spec.request_id,
                    payload={"reason": "cancelled while running"},
                )
            )
            raise
        except Exception as exc:
            summary = f"{type(exc).__name__}: {exc}"
            logger.error(
                "Agent %s (%s) failed: %s",
                spec.agent_id,
                spec.kind,
                summary,
                exc_info=True,
            )
            await self._settle(
                spec.agent_id,
                "failed",
                request_id=spec.request_id,
                error=summary,
                payload={"error": summary},
            )
        else:
            await self._settle(
                spec.agent_id,
                "completed",
                request_id=spec.request_id,
                result=result,
            )

    async def _settle(
        self,
        agent_id: str,
        state: str,
        *,
        request_id: str | None,
        result: AgentResult | None = None,
        error: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """One terminal transition, mirrored to live state and audit.

        The store enforces terminal-wins, so whichever settle lands first
        (e.g. cancel-while-pending vs. shutdown) is the only one recorded.
        """
        snapshot = await self._store.update_agent(
            agent_id,
            state=state,
            progress_fraction=1.0 if state == "completed" else None,
            last_result=None if result is None else result.summary,
            error=error,
        )
        if snapshot is None:
            return
        if result is not None:
            payload = {"summary": result.summary, "result": result.payload}
        self._audit.record_agent_event(
            agent_id, state, request_id=request_id, state=state, payload=payload
        )

    # -- context wiring -------------------------------------------------------------

    def _progress_reporter(self, spec: AgentSpec):
        async def report(
            phase: str, *, fraction: float | None = None, detail: str | None = None
        ) -> None:
            await self._store.update_agent(
                spec.agent_id, progress_phase=phase, progress_fraction=fraction
            )
            self._audit.record_agent_event(
                spec.agent_id,
                "progress",
                request_id=spec.request_id,
                state="running",
                payload={"phase": phase, "fraction": fraction, "detail": detail},
            )

        return report

    def _audit_emitter(self, spec: AgentSpec):
        def emit(event_type: str, *, payload: dict[str, Any] | None = None) -> None:
            self._audit.record_agent_event(
                spec.agent_id,
                event_type,
                request_id=spec.request_id,
                state="running",
                payload=payload,
            )

        return emit
