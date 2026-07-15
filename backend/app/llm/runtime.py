"""Single global llama.cpp runtime.

The architecture's core rule (docs/Architecture.md): one in-process
``llama_cpp.Llama`` instance, created once by the ``main.py`` lifespan handler
and shared by every execution path. ``llama_cpp`` must never be imported
outside ``app.llm`` — callers depend on :class:`LlamaRuntime` via
:func:`get_llm_runtime`.

Concurrency model: ``llama.cpp`` inference is blocking and not safe to call
concurrently on one instance. :meth:`LlamaRuntime.generate` therefore
serializes all calls and runs the actual completion in a worker thread, so the
event loop — and with it ``/api/health`` — stays responsive while a generation
is in flight.

Scheduling (Step 14): foreground (main-graph) generations take priority over
background agent ones. Calls marked ``background=True`` only acquire the
model when no foreground caller is waiting, so a prompt request queues behind
at most the single generation already in flight — never behind a backlog of
agent work. Within each priority class the order is FIFO; an in-flight
generation is never preempted.
"""

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from fastapi import Request

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def load_system_prompt(name: str = "system") -> str:
    """Read a prompt template from ``app/llm/prompts/<name>.md``."""
    return (_PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8").strip()


class _PriorityGate:
    """A mutex with two FIFO wait queues: foreground acquirers always get the
    next turn ahead of queued background ones (see module docstring).

    Same hand-off discipline as ``asyncio.Lock``: :meth:`release` transfers
    ownership directly to the chosen waiter, and a waiter cancelled after the
    hand-off passes the lock on instead of leaking it. ``release`` is
    deliberately synchronous so it is always safe in a ``finally``.
    """

    def __init__(self) -> None:
        self._locked = False
        self._foreground: deque[asyncio.Future[None]] = deque()
        self._background: deque[asyncio.Future[None]] = deque()

    async def acquire(self, *, background: bool = False) -> None:
        if not self._locked:
            self._locked = True
            return
        fut: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        queue = self._background if background else self._foreground
        queue.append(fut)
        try:
            await fut
        except asyncio.CancelledError:
            if fut.done() and not fut.cancelled():
                # The lock was handed to us just as we were cancelled: pass
                # it straight to the next waiter.
                self.release()
            else:
                queue.remove(fut)
            raise
        # Ownership was transferred by release(); _locked is still True.

    def release(self) -> None:
        for queue in (self._foreground, self._background):
            while queue:
                fut = queue.popleft()
                if not fut.done():
                    fut.set_result(None)
                    return
        self._locked = False


class ModelNotFoundError(RuntimeError):
    """The configured GGUF model file does not exist."""

    def __init__(self, model_path: str) -> None:
        super().__init__(
            f"Model file not found: {model_path!r}. Fetch the default model "
            "with scripts/download_model.ps1 (or .sh), or point MODEL_PATH "
            "in .env at an existing GGUF file."
        )
        self.model_path = model_path


@dataclass(frozen=True, slots=True)
class GenerationResult:
    """One completed generation plus the metadata the audit layer persists."""

    text: str
    model_id: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    duration_ms: float
    finish_reason: str | None = None

    def usage(self) -> dict[str, Any]:
        """Usage dict shaped for ``AuditService.record_prompt_response``."""
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "duration_ms": self.duration_ms,
            "finish_reason": self.finish_reason,
        }


class LlamaRuntime:
    """Wrapper around one shared ``llama_cpp.Llama`` instance.

    ``llama_factory`` exists for tests only: it replaces the ``Llama`` class
    so the suite runs without a model file or the ``llama-cpp-python``
    package installed.
    """

    def __init__(
        self,
        *,
        model_path: str,
        context_size: int = 4096,
        gpu_layers: int = 0,
        max_tokens: int = 512,
        temperature: float = 0.7,
        llama_factory: Callable[..., Any] | None = None,
    ) -> None:
        self._model_path = model_path
        self._context_size = context_size
        self._gpu_layers = gpu_layers
        self._defaults: dict[str, Any] = {
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        self._llama_factory = llama_factory
        self._llama: Any = None
        self._model_id = Path(model_path).name
        # Serializes all inference on the single Llama instance, foreground
        # callers first (Step 14).
        self._gate = _PriorityGate()

    # -- lifecycle -----------------------------------------------------------

    def load(self) -> None:
        """Load the model; blocking, called once from lifespan startup."""
        path = Path(self._model_path)
        if not path.is_file():
            raise ModelNotFoundError(self._model_path)
        factory = self._llama_factory
        if factory is None:
            from llama_cpp import Llama  # the only llama_cpp import in the codebase

            factory = Llama
        started = time.perf_counter()
        self._llama = factory(
            model_path=str(path),
            n_ctx=self._context_size,
            n_gpu_layers=self._gpu_layers,
            verbose=False,
        )
        logger.info(
            "Model loaded: %s (context_size=%d, gpu_layers=%d, "
            "max_tokens=%d, temperature=%.2f) in %.1fs",
            self._model_id,
            self._context_size,
            self._gpu_layers,
            self._defaults["max_tokens"],
            self._defaults["temperature"],
            time.perf_counter() - started,
        )

    def close(self) -> None:
        """Release the model; called from lifespan shutdown."""
        llama, self._llama = self._llama, None
        if llama is not None and hasattr(llama, "close"):
            llama.close()

    # -- introspection (health checks) ---------------------------------------

    @property
    def loaded(self) -> bool:
        return self._llama is not None

    @property
    def model_info(self) -> dict[str, Any]:
        return {
            "model_id": self._model_id,
            "model_path": self._model_path,
            "context_size": self._context_size,
            "gpu_layers": self._gpu_layers,
            "loaded": self.loaded,
        }

    # -- inference ------------------------------------------------------------

    def _release_after_abandoned(self, work: "asyncio.Future[Any]") -> None:
        """Release the gate once an abandoned generation's thread finishes."""
        self._gate.release()
        if not work.cancelled() and work.exception() is not None:
            logger.error("Abandoned generation failed: %s", work.exception())

    async def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        background: bool = False,
        **overrides: Any,
    ) -> GenerationResult:
        """Run one chat completion; calls serialize, the event loop does not
        block. ``background=True`` marks a background-agent call, which yields
        the next turn to any waiting foreground caller (see module docstring).
        ``overrides`` are per-call generation params (``max_tokens``,
        ``temperature``, ...) layered over the configured defaults."""
        if not self.loaded:
            raise RuntimeError("LlamaRuntime.generate() called before load()")
        messages: list[dict[str, str]] = []
        if system is not None:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        params = {**self._defaults, **overrides}

        await self._gate.acquire(background=background)
        started = time.perf_counter()
        work = asyncio.ensure_future(
            asyncio.to_thread(
                self._llama.create_chat_completion, messages=messages, **params
            )
        )
        try:
            completion = await asyncio.shield(work)
        except asyncio.CancelledError:
            # The caller was cancelled (e.g. a background agent), but the
            # inference thread cannot be interrupted: keep the gate held
            # until it actually finishes, so no other call ever enters
            # llama.cpp concurrently.
            work.add_done_callback(self._release_after_abandoned)
            raise
        except BaseException:
            self._gate.release()
            raise
        else:
            self._gate.release()
        duration_ms = (time.perf_counter() - started) * 1000

        choice = completion["choices"][0]
        usage = completion.get("usage") or {}
        return GenerationResult(
            text=(choice["message"].get("content") or ""),
            model_id=self._model_id,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            duration_ms=duration_ms,
            finish_reason=choice.get("finish_reason"),
        )


def get_llm_runtime(request: Request) -> LlamaRuntime:
    """FastAPI dependency: the process-wide runtime built in the lifespan."""
    return request.app.state.llm_runtime
