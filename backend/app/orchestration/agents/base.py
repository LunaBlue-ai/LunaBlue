"""The background-agent lifecycle contract (Step 14).

An agent is a long-running unit of work spawned by the main graph and executed
by the :class:`~app.orchestration.runner.AgentRunner`. This module defines the
three pieces every agent implementation shares:

- :class:`AgentSpec` — the immutable description of one spawned agent: what
  kind of work, for which request/session, with which parameters.
- The lifecycle states (re-exported from :mod:`app.state.store`):
  ``pending → running → completed | failed | cancelled``. The runner drives
  every transition; agents only report progress within ``running``.
- :class:`BackgroundAgent` — the base class each agent implements: one async
  :meth:`~BackgroundAgent.run` receiving an :class:`AgentContext`.

Dependency rule (docs/Architecture.md): agents never construct their own
dependencies. The context carries the injected shared
:class:`~app.llm.runtime.LlamaRuntime` (via :meth:`AgentContext.generate`,
which marks every call background-priority), read handles on the
:class:`~app.state.store.StateStore`, a progress reporter that feeds both the
store and the audit trail, and an audit emitter for agent-specific events.
"""

import abc
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, ClassVar, Mapping

from app.llm.runtime import GenerationResult, LlamaRuntime
from app.state.store import (  # noqa: F401  (re-exported lifecycle vocabulary)
    AGENT_STATES,
    TERMINAL_AGENT_STATES,
    StateStore,
)


def _new_agent_id() -> str:
    return str(uuid.uuid4())


@dataclass(frozen=True, slots=True)
class AgentSpec:
    """Immutable description of one spawned background agent."""

    kind: str  # registered agent type (e.g. "research")
    task: str  # human-readable description of the work
    agent_id: str = field(default_factory=_new_agent_id)
    request_id: str | None = None  # prompt run that spawned the agent
    session_id: str | None = None
    params: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )  # kind-specific knobs; must stay JSON-safe (they are audited verbatim)


@dataclass(frozen=True, slots=True)
class AgentResult:
    """What a completed agent produced.

    ``summary`` lands in live state (``AgentSnapshot.last_result``);
    ``payload`` is the full JSON-safe result, persisted on the ``completed``
    audit event.
    """

    summary: str
    payload: dict[str, Any] = field(default_factory=dict)


# The runner-provided reporting callbacks (bound to one agent execution).
ProgressReporter = Callable[..., Awaitable[None]]
AuditEmitter = Callable[..., None]


class AgentContext:
    """Everything one agent execution may touch, injected by the runner."""

    def __init__(
        self,
        *,
        spec: AgentSpec,
        runtime: LlamaRuntime,
        store: StateStore,
        report_progress: ProgressReporter,
        emit_audit: AuditEmitter,
    ) -> None:
        self.spec = spec
        self.store = store  # read handles (snapshots); mutations are the runner's
        self._runtime = runtime
        self._report_progress = report_progress
        self._emit_audit = emit_audit

    async def generate(
        self, prompt: str, *, system: str | None = None, **overrides: Any
    ) -> GenerationResult:
        """One LLM call on the single shared runtime, at background priority:
        foreground (main-graph) generations always get the next turn first."""
        return await self._runtime.generate(
            prompt, system=system, background=True, **overrides
        )

    async def report_progress(
        self, phase: str, *, fraction: float | None = None, detail: str | None = None
    ) -> None:
        """Report a progress step. The runner writes it to both the live
        agent registry (publishing ``agent_updated``) and the audit trail."""
        await self._report_progress(phase, fraction=fraction, detail=detail)

    def audit(
        self, event_type: str, *, payload: dict[str, Any] | None = None
    ) -> None:
        """Emit an agent-specific audit event (agent id, request id, and
        current lifecycle state are filled in by the runner)."""
        self._emit_audit(event_type, payload=payload)


class BackgroundAgent(abc.ABC):
    """Base class for background agents executed by the ``AgentRunner``.

    Implementations declare their registered ``kind`` and do all their work in
    :meth:`run` using only the context's injected dependencies. Lifecycle is
    the runner's job: raise to fail the agent, return an :class:`AgentResult`
    to complete it, and let :class:`asyncio.CancelledError` propagate so
    cancellation stays clean.
    """

    kind: ClassVar[str]

    @abc.abstractmethod
    async def run(self, context: AgentContext) -> AgentResult:
        """Execute the task described by ``context.spec``."""
