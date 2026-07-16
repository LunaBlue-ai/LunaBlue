"""Shared in-memory fakes and app wiring helpers: the suite runs without
Postgres, a model file, or the ``llama-cpp-python`` package."""

import time
from dataclasses import dataclass, field
from typing import Any

from httpx import ASGITransport, AsyncClient

from app.audit.service import AgentEvent
from app.governance.intake import PromptIntake
from app.governance.policy import PolicyEngine
from app.llm.runtime import LlamaRuntime
from app.main import create_app
from app.orchestration.pipeline import PromptPipeline
from app.orchestration.runner import AgentRunner
from app.state.events import EventBus
from app.state.store import StateStore


class FakeLlama:
    """Mimics ``llama_cpp.Llama`` closely enough for the tests.

    Knobs: ``block_seconds`` simulates slow blocking inference,
    ``fail_with`` makes the next completions raise, ``queued_responses``
    replaces the default ``echo:`` reply (popped in order, one per call) —
    e.g. to feed the review node a JSON verdict.
    """

    def __init__(self, *, model_path, n_ctx, n_gpu_layers, verbose, **_):
        self.model_path = model_path
        self.n_ctx = n_ctx
        self.n_gpu_layers = n_gpu_layers
        self.calls: list[dict] = []
        self.busy = False
        self.concurrent_entry = False
        self.block_seconds = 0.0
        self.fail_with: Exception | None = None
        self.queued_responses: list[str] = []
        self.closed = False

    def create_chat_completion(self, *, messages, **params):
        if self.busy:
            # Two threads inside the (not concurrency-safe) instance at once.
            self.concurrent_entry = True
        self.busy = True
        try:
            if self.block_seconds:
                time.sleep(self.block_seconds)  # simulates blocking inference
            if self.fail_with is not None:
                raise self.fail_with
            self.calls.append({"messages": messages, **params})
            user = next(m["content"] for m in messages if m["role"] == "user")
            content = (
                self.queued_responses.pop(0)
                if self.queued_responses
                else f"echo: {user}"
            )
            return {
                "choices": [
                    {
                        "message": {"content": content},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 7,
                    "completion_tokens": 3,
                    "total_tokens": 10,
                },
            }
        finally:
            self.busy = False

    def close(self):
        self.closed = True


class FakeLlamaRuntime(LlamaRuntime):
    """Drop-in for :class:`LlamaRuntime` that needs no model file and never
    imports ``llama_cpp``: only the blocking inference is faked, so the real
    scheduling, serialization, and metadata code all still run.

    Configure per test through :attr:`fake` (a :class:`FakeLlama`): queue
    scripted responses via ``fake.queued_responses``, simulate latency via
    ``fake.block_seconds``, and failure via ``fake.fail_with``. Received
    prompts are recorded in ``fake.calls`` / :attr:`prompts`.
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(
            model_path="model.gguf", llama_factory=FakeLlama, **kwargs
        )
        self.fake: FakeLlama | None = None

    def load(self) -> None:
        # The real load() insists the model file exists; the fake needs none.
        # GPU offload support stays None (unknown): the fake never probes
        # llama_cpp, so model_info reports gpu_offload_supported=None.
        self.fake = FakeLlama(
            model_path=self._model_path,
            n_ctx=self._context_size,
            n_gpu_layers=self._gpu_layers,
            verbose=False,
        )
        self._llama = self.fake

    @property
    def prompts(self) -> list[str]:
        """User-turn content of every completed generation, in call order."""
        assert self.fake is not None, "load() has not run"
        return [
            next(m["content"] for m in call["messages"] if m["role"] == "user")
            for call in self.fake.calls
        ]


def make_runtime(tmp_path, **kwargs) -> tuple[LlamaRuntime, FakeLlama]:
    """A loaded runtime backed by FakeLlama and a real (empty) model file."""
    model_file = tmp_path / "model.gguf"
    model_file.write_bytes(b"gguf")
    holder: list[FakeLlama] = []

    def factory(**factory_kwargs):
        fake = FakeLlama(**factory_kwargs)
        holder.append(fake)
        return fake

    runtime = LlamaRuntime(
        model_path=str(model_file), llama_factory=factory, **kwargs
    )
    runtime.load()
    return runtime, holder[0]


@dataclass
class FakeAuditService:
    """Records emitted audit events in memory for assertion."""

    sessions: list[dict[str, Any]] = field(default_factory=list)
    prompt_requests: list[dict[str, Any]] = field(default_factory=list)
    prompt_responses: list[dict[str, Any]] = field(default_factory=list)
    agent_events: list[dict[str, Any]] = field(default_factory=list)

    def record_session(self, session_id, *, user_id=None, metadata=None):
        self.sessions.append(
            {"session_id": session_id, "user_id": user_id, "metadata": metadata}
        )

    def record_prompt_request(
        self, request_id, raw_prompt, *, session_id=None, user_id=None, **kwargs
    ):
        self.prompt_requests.append(
            {
                "request_id": request_id,
                "raw_prompt": raw_prompt,
                "session_id": session_id,
                "user_id": user_id,
                **kwargs,
            }
        )

    def record_prompt_response(self, request_id, **kwargs):
        self.prompt_responses.append({"request_id": request_id, **kwargs})

    # AgentEvent dataclasses mirroring agent_events rows (timestamped at
    # record time), backing the fetch_agent_events read path.
    _agent_event_rows: list[AgentEvent] = field(default_factory=list)

    def record_agent_event(
        self, agent_id, event_type, *, request_id=None, state=None, payload=None
    ):
        self.agent_events.append(
            {
                "agent_id": agent_id,
                "event_type": event_type,
                "request_id": request_id,
                "state": state,
                "payload": payload,
            }
        )
        self._agent_event_rows.append(
            AgentEvent(
                agent_id=agent_id,
                event_type=event_type,
                request_id=request_id,
                state=state,
                payload=payload,
            )
        )

    async def fetch_agent_events(self, agent_id, *, limit=200) -> list[AgentEvent]:
        """In-memory mirror of ``AuditService.fetch_agent_events``: the most
        recent events for one agent, returned oldest first."""
        rows = [e for e in self._agent_event_rows if e.agent_id == agent_id]
        return rows[-limit:] if limit > 0 else rows

    def events_for(self, agent_id) -> list[dict[str, Any]]:
        """The audited lifecycle for one agent, in emission order."""
        return [e for e in self.agent_events if e["agent_id"] == agent_id]

    # Introspection surface readiness reads (Step 17); the in-memory fake
    # never overflows.
    saturated: bool = False
    dropped_total: int = 0
    queue_capacity: int = 1000

    @property
    def queue_depth(self) -> int:
        return 0


def make_app(
    audit,
    runtime,
    *,
    strict: bool = False,
    timeout: float = 5.0,
    store: StateStore | None = None,
    max_queue_depth: int = 0,
    agent_timeout: float = 0.0,
    agent_max_steps: int = 0,
):
    """App instance wired like the lifespan does, with fakes (no lifespan).

    The Step 17 guards (``max_queue_depth``, ``agent_timeout``,
    ``agent_max_steps``) default to disabled so happy-path tests are
    unaffected; guard tests opt in per instance.
    """
    app = create_app()
    intake = PromptIntake(PolicyEngine(strict_mode=strict))
    if store is None:
        store = StateStore(max_finished_runs=64)
    event_bus = EventBus()
    store.set_notify(event_bus.publish)
    app.state.audit_service = audit
    app.state.prompt_intake = intake
    app.state.llm_runtime = runtime
    app.state.state_store = store
    app.state.event_bus = event_bus
    # Not started here (starting workers needs a running loop); tests that
    # exercise agent execution call app.state.agent_runner.start() themselves.
    runner = AgentRunner(
        runtime=runtime,
        store=store,
        audit=audit,
        timeout_seconds=agent_timeout,
        max_steps=agent_max_steps,
    )
    app.state.agent_runner = runner
    app.state.prompt_pipeline = PromptPipeline(
        intake=intake,
        runtime=runtime,
        audit=audit,
        store=store,
        timeout_seconds=timeout,
        runner=runner,
        max_queue_depth=max_queue_depth,
    )
    return app


def make_client(
    audit,
    runtime,
    *,
    strict: bool = False,
    timeout: float = 5.0,
    store: StateStore | None = None,
    max_queue_depth: int = 0,
) -> AsyncClient:
    """HTTP client over a fake-wired app (see :func:`make_app`)."""
    app = make_app(
        audit,
        runtime,
        strict=strict,
        timeout=timeout,
        store=store,
        max_queue_depth=max_queue_depth,
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
