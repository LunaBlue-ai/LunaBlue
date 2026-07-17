"""Background rolling-summary maintenance (closed-loop prompt processing).

After each completed prompt run the pipeline schedules a summary update: the
local LLM folds the raw user prompt and a short excerpt of the response into
the session's rolling summary (``app/llm/prompts/summarize_session.md``),
capped at a configured character budget, and the result is written back to
the :class:`~app.state.store.StateStore` for the next turn to inject.

Fire-and-forget by design: :meth:`SessionSummarizer.schedule` never raises
and never blocks the caller, updates for the same session run strictly in
submission order (each task awaits the previous tail), and a failed update
logs a warning and keeps the previous summary. Generation runs at background
priority so foreground prompts always win the model.
"""

import asyncio
import logging
from typing import Any

from app.llm.runtime import LlamaRuntime, load_system_prompt
from app.state.store import StateStore

logger = logging.getLogger(__name__)

_TEMPLATE_NAME = "summarize_session"

# Summarization is compression, not creative generation.
_SUMMARIZE_PARAMS: dict[str, Any] = {"temperature": 0.2}

# Input excerpts are truncated so the summarize call always fits the small
# default context window (LLM_CONTEXT_SIZE=4096).
_PROMPT_EXCERPT_CHARS = 1000
_RESPONSE_EXCERPT_CHARS = 500


class SessionSummarizer:
    """Maintains each session's internal rolling chat summary in the store."""

    def __init__(
        self,
        *,
        runtime: LlamaRuntime,
        store: StateStore,
        max_chars: int = 2000,
        max_tokens: int = 600,
    ) -> None:
        self._runtime = runtime
        self._store = store
        self._max_chars = max_chars
        self._max_tokens = max_tokens
        # Per-session chain tail: each new update awaits the previous one for
        # that session, so updates apply in submission order without a lock.
        self._tails: dict[str, asyncio.Task] = {}
        self._tasks: set[asyncio.Task] = set()
        # Per-session reset epoch (Step 20): schedule() captures it, _run()
        # discards its write when a reset bumped it in the meantime — so an
        # in-flight update can never resurrect a cleared summary. One int per
        # session ever seen, same lifetime profile as the store's sessions.
        self._epochs: dict[str, int] = {}
        self._closed = False

    def schedule(
        self, session_id: str, *, user_prompt: str, response_text: str
    ) -> None:
        """Queue a summary update for one completed turn. Never raises."""
        if self._closed:
            return
        prev = self._tails.get(session_id)
        epoch = self._epochs.get(session_id, 0)
        task = asyncio.create_task(
            self._run(prev, session_id, user_prompt, response_text, epoch)
        )
        self._tails[session_id] = task
        self._tasks.add(task)

        def _done(finished: asyncio.Task) -> None:
            self._tasks.discard(finished)
            if self._tails.get(session_id) is finished:
                del self._tails[session_id]
            if not finished.cancelled():
                finished.exception()  # consume; _run already contained it

        task.add_done_callback(_done)

    async def reset(self, session_id: str) -> None:
        """Clear the session's rolling summary and invalidate in-flight
        updates (the reset endpoint, Step 20).

        Pending tasks are not cancelled — they settle normally and simply
        skip their store write when they see the bumped epoch.
        """
        self._epochs[session_id] = self._epochs.get(session_id, 0) + 1
        await self._store.set_session_summary(session_id, "")

    async def wait_idle(self) -> None:
        """Wait for every scheduled update to settle (tests)."""
        while self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)

    async def aclose(self) -> None:
        """Cancel pending updates and stop accepting new ones (shutdown).

        Summaries are disposable in-memory state, so cancellation is safe.
        """
        self._closed = True
        pending = tuple(self._tasks)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async def _run(
        self,
        prev: asyncio.Task | None,
        session_id: str,
        user_prompt: str,
        response_text: str,
        epoch: int,
    ) -> None:
        if prev is not None:
            await asyncio.gather(prev, return_exceptions=True)
        if self._epochs.get(session_id, 0) != epoch:
            return  # reset since scheduled: skip the wasted generation
        try:
            current = self._store.get_session_summary(session_id) or ""
            instructions = load_system_prompt(_TEMPLATE_NAME).replace(
                "{max_chars}", str(self._max_chars)
            )
            prompt = (
                f"{instructions}\n\n"
                f"Current summary:\n---\n{current or '(none)'}\n---\n"
                f"Latest user message:\n---\n"
                f"{user_prompt[:_PROMPT_EXCERPT_CHARS]}\n---\n"
                f"Latest assistant reply:\n---\n"
                f"{response_text[:_RESPONSE_EXCERPT_CHARS]}\n---"
            )
            result = await self._runtime.generate(
                prompt,
                background=True,
                max_tokens=self._max_tokens,
                **_SUMMARIZE_PARAMS,
            )
            updated = result.text.strip()
            if not updated:
                logger.warning(
                    "Session %s: summary update produced no text; keeping "
                    "the previous summary.",
                    session_id,
                )
                return
            if len(updated) > self._max_chars:
                updated = updated[: self._max_chars - 1] + "…"
            if self._epochs.get(session_id, 0) != epoch:
                # The correctness-critical check: a reset landed while the
                # generate call was in flight — discard, don't resurrect.
                logger.debug(
                    "Session %s: discarding stale summary update (reset "
                    "since scheduled).",
                    session_id,
                )
                return
            await self._store.set_session_summary(session_id, updated)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Failure containment: the rolling summary is best-effort — a
            # failed update must never surface anywhere.
            logger.warning(
                "Session %s: summary update failed; keeping the previous "
                "summary: %s: %s",
                session_id,
                type(exc).__name__,
                exc,
            )
