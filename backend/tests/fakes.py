"""Shared in-memory fakes and app wiring helpers: the suite runs without
Postgres, a model file, or the ``llama-cpp-python`` package."""

import time
from dataclasses import dataclass, field
from typing import Any

from httpx import ASGITransport, AsyncClient

from app.governance.intake import PromptIntake
from app.governance.policy import PolicyEngine
from app.llm.runtime import LlamaRuntime
from app.main import create_app
from app.orchestration.pipeline import PromptPipeline
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


def make_app(
    audit,
    runtime,
    *,
    strict: bool = False,
    timeout: float = 5.0,
    store: StateStore | None = None,
):
    """App instance wired like the lifespan does, with fakes (no lifespan)."""
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
    app.state.prompt_pipeline = PromptPipeline(
        intake=intake,
        runtime=runtime,
        audit=audit,
        store=store,
        timeout_seconds=timeout,
    )
    return app


def make_client(
    audit,
    runtime,
    *,
    strict: bool = False,
    timeout: float = 5.0,
    store: StateStore | None = None,
) -> AsyncClient:
    """HTTP client over a fake-wired app (see :func:`make_app`)."""
    app = make_app(audit, runtime, strict=strict, timeout=timeout, store=store)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
