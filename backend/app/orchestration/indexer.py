"""Background embedding indexer.

Mirrors :class:`app.orchestration.summarizer.SessionSummarizer`'s
fire-and-forget task pattern: :meth:`EmbeddingIndexer.schedule` never raises
and never blocks the caller; each scheduled item embeds its text on the
dedicated embedding runtime and writes the vector + metadata row in one
transaction. Failures are contained and logged — embeddings are an
enhancement, not part of the audited record.

Scheduled by :class:`app.audit.service.AuditService` *after* a batch
commits, so the ``prompt_requests`` row an embedding references always
exists (FK) and the embedded text is exactly the stored (possibly
redacted) text — the live path and the backfill CLI embed identical
inputs.
"""

import asyncio
import logging

from app.audit import db, vectors
from app.llm.embedding import EmbeddingRuntime

logger = logging.getLogger(__name__)

_DEFAULT_MAX_PENDING = 64


class EmbeddingIndexer:
    """Fire-and-forget embedding writes for persisted prompts/responses."""

    def __init__(
        self,
        runtime: EmbeddingRuntime,
        *,
        max_pending: int = _DEFAULT_MAX_PENDING,
    ) -> None:
        self._runtime = runtime
        self._max_pending = max_pending
        self._tasks: set[asyncio.Task] = set()
        self._closed = False
        self._dropped_total = 0

    @property
    def pending(self) -> int:
        return len(self._tasks)

    @property
    def dropped_total(self) -> int:
        return self._dropped_total

    def schedule(self, kind: str, request_id: str, text: str | None) -> None:
        """Queue one embedding write. Never raises, never blocks.

        Silently skips empty text (failed runs store NULL outputs) and an
        unavailable runtime; drops with a warning when the backlog exceeds
        ``max_pending`` (mirrors the audit queue's bounded philosophy).
        """
        if self._closed or not text or not self._runtime.available:
            return
        if len(self._tasks) >= self._max_pending:
            self._dropped_total += 1
            logger.warning(
                "Embedding indexer backlog full (%d pending) - dropping "
                "%s embedding for request %s. The backfill script can "
                "re-embed skipped rows later.",
                len(self._tasks),
                kind,
                request_id,
            )
            return
        task = asyncio.create_task(self._run(kind, request_id, text))
        self._tasks.add(task)

        def _done(finished: asyncio.Task) -> None:
            self._tasks.discard(finished)
            if not finished.cancelled():
                finished.exception()  # consume; _run already contained it

        task.add_done_callback(_done)

    async def wait_idle(self) -> None:
        """Wait for every scheduled write to settle (tests)."""
        while self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)

    async def aclose(self) -> None:
        """Cancel pending writes and stop accepting new ones (shutdown).

        Unembedded rows are recoverable via the backfill script, so
        cancellation is safe.
        """
        self._closed = True
        pending = tuple(self._tasks)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async def _run(self, kind: str, request_id: str, text: str) -> None:
        try:
            [vector] = await self._runtime.embed(
                [text], prefix="search_document"
            )
            async with db.session_scope() as session:
                await vectors.insert_embedding(
                    session,
                    request_id=request_id,
                    kind=kind,
                    model_id=self._runtime.model_info["model_id"],
                    vector=vector,
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "Embedding write failed for request %s (%s): %s",
                request_id,
                kind,
                exc,
            )
