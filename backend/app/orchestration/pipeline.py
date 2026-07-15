"""The prompt pipeline: the seam between ``POST /api/prompt`` and orchestration.

:class:`PromptPipeline` owns the full request flow — governance intake, the
LangGraph main graph (Step 9), and the audit chain — so the route stays
routing-only per docs/Components/API.md. Generation now runs through the
graph in :mod:`app.orchestration.graph` (prompt engineering → LLM review →
respond), which means **two LLM calls per request** (review + respond); the
configured timeout bounds the whole graph run, not each call.

Failure contract (unchanged from Step 8): prompts rejected by intake raise
:class:`~app.governance.intake.PromptRejectedError` (audited here, mapped to
400 by the route). A generation failure or timeout inside any graph node
raises :class:`GenerationFailedError` after auditing a failed
``PromptResponseEvent``; the route maps them to a 5xx with
``status="failed"``. Neither leaves the service unhealthy.

The audited ``PromptResponseEvent`` for a successful run carries the graph's
accumulated decision metadata (per-node records: engineering transformations,
review outcome, synthesis details, timings) under ``usage["decisions"]``.

Step 10: the pipeline also drives the shared :class:`~app.state.store.StateStore`
— it starts the run (``received``), marks ``governance``, and settles it
(``completed``/``failed``); the graph's node wrappers advance the phases in
between. Live status is served from the store by ``GET /api/runs/{id}``.
"""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from fastapi import Request

from app.audit.service import AuditService
from app.governance.intake import IntakeContext, PromptIntake, PromptRejectedError
from app.llm.runtime import LlamaRuntime
from app.orchestration.graph import MainGraphState, build_main_graph
from app.orchestration.runner import AgentRunner
from app.state.store import StateStore

logger = logging.getLogger(__name__)

# Cap on the result summary stored in live run state; the full output lives in
# the audit record.
_SUMMARY_MAX_CHARS = 200


def _summarize(text: str) -> str:
    if len(text) <= _SUMMARY_MAX_CHARS:
        return text
    return text[: _SUMMARY_MAX_CHARS - 1] + "…"


@dataclass(frozen=True, slots=True)
class PipelineResult:
    """The outcome of a successful pipeline run; the route wraps it into the
    ``PromptResponse`` wire format."""

    request_id: str
    session_id: str
    response_text: str
    created_at: datetime


class GenerationFailedError(Exception):
    """Generation failed or timed out after the request was accepted.

    Raised only after the failure has been audited. Carries the identifiers
    the route needs to build the ``status="failed"`` response body; ``summary``
    is the internal error description (already audited — not for clients).
    """

    def __init__(
        self,
        summary: str,
        *,
        request_id: str,
        session_id: str,
        created_at: datetime,
    ) -> None:
        super().__init__(summary)
        self.summary = summary
        self.request_id = request_id
        self.session_id = session_id
        self.created_at = created_at


def _log_abandoned_run(task: asyncio.Task) -> None:
    """Consume the result of a graph run whose request already timed out."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error("Abandoned graph run also failed: %s", exc)
    else:
        logger.warning("Abandoned graph run completed after its request timed out")


class PromptPipeline:
    """Owns the governance → main graph → audit sequence for one prompt
    request."""

    def __init__(
        self,
        *,
        intake: PromptIntake,
        runtime: LlamaRuntime,
        audit: AuditService,
        store: StateStore,
        timeout_seconds: float,
        runner: AgentRunner | None = None,
    ) -> None:
        self._intake = intake
        self._runtime = runtime
        self._audit = audit
        self._store = store
        self._timeout_seconds = timeout_seconds
        # Compiled once per process (the lifespan builds one pipeline); the
        # store bound here makes each node entry advance the run's phase, and
        # the runner (Step 14) enables the agent-spawn detour.
        self._graph = build_main_graph(runtime, store, runner)

    async def run(
        self,
        text: str,
        *,
        session_id: str | None = None,
        user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> PipelineResult:
        """Execute the full flow for one validated prompt."""
        request_id = str(uuid.uuid4())
        session_id = session_id or str(uuid.uuid4())
        created_at = datetime.now(timezone.utc)

        # Live state first: the run (and its session) become observable via
        # the status APIs before any processing happens.
        await self._store.start_run(request_id, session_id, user_id=user_id)

        # SessionEvent upserts, so emitting unconditionally both creates new
        # sessions and touches existing ones — and, because audit events are
        # written in order, guarantees the session row exists before the
        # prompt_requests FK references it.
        self._audit.record_session(session_id, user_id=user_id, metadata=metadata)

        await self._store.update_run_phase(request_id, "governance")
        context = IntakeContext(
            session_id=session_id, user_id=user_id, metadata=metadata
        )
        try:
            reviewed = self._intake.review(text, context)
        except PromptRejectedError as exc:
            # Rejections are audited too: raw text untouched, plus whatever
            # the intake produced before rejecting and the governance
            # metadata carrying the rejected decision.
            await self._store.fail_run(
                request_id, f"Rejected by governance: {exc.reason}"
            )
            self._audit.record_prompt_request(
                request_id,
                text,
                session_id=session_id,
                user_id=user_id,
                reviewed_prompt=exc.reviewed_text,
                prompt_version=exc.prompt_version,
                governance=exc.metadata.to_dict(),
            )
            raise

        self._audit.record_prompt_request(
            request_id,
            text,
            session_id=session_id,
            user_id=user_id,
            reviewed_prompt=reviewed.reviewed_text,
            prompt_version=reviewed.prompt_version,
            governance=reviewed.governance.to_dict(),
        )

        initial: MainGraphState = {
            "request_id": request_id,
            "session_id": session_id,
            "reviewed_prompt": reviewed.reviewed_text,
            "governance": reviewed.governance,
            "decisions": [],
        }
        started = time.perf_counter()
        try:
            state = await self._invoke_graph(initial)
        except Exception as exc:
            duration_ms = (time.perf_counter() - started) * 1000
            if isinstance(exc, asyncio.TimeoutError):
                summary = (
                    f"Generation timed out after {self._timeout_seconds:.1f}s"
                )
                logger.error("Request %s: %s", request_id, summary)
            else:
                summary = f"{type(exc).__name__}: {exc}"
                logger.error(
                    "Request %s: generation failed: %s",
                    request_id,
                    summary,
                    exc_info=True,
                )
            await self._store.fail_run(request_id, summary)
            self._audit.record_prompt_response(
                request_id,
                model_id=self._runtime.model_info["model_id"],
                usage={
                    "status": "failed",
                    "error": summary,
                    "duration_ms": duration_ms,
                },
            )
            raise GenerationFailedError(
                summary,
                request_id=request_id,
                session_id=session_id,
                created_at=created_at,
            ) from exc

        await self._store.complete_run(
            request_id, result_summary=_summarize(state["final_output"])
        )
        # The response event carries the synthesis usage plus the per-node
        # decision metadata the graph accumulated.
        self._audit.record_prompt_response(
            request_id,
            llm_output=state["draft_output"],
            final_output=state["final_output"],
            model_id=state["model_id"],
            usage={**state["usage"], "decisions": state["decisions"]},
        )
        return PipelineResult(
            request_id=request_id,
            session_id=session_id,
            response_text=state["final_output"],
            created_at=created_at,
        )

    async def _invoke_graph(self, initial: MainGraphState) -> MainGraphState:
        """Run the main graph under the configured timeout.

        The run is shielded: cancelling it mid-generation would release the
        runtime lock while the inference thread is still inside llama.cpp,
        letting a later request enter it concurrently. On timeout the
        abandoned run keeps the lock until its thread finishes (later requests
        queue behind it) and its outcome is logged and discarded.
        """
        task = asyncio.ensure_future(self._graph.ainvoke(initial))
        try:
            return await asyncio.wait_for(
                asyncio.shield(task), self._timeout_seconds
            )
        except (asyncio.TimeoutError, asyncio.CancelledError):
            task.add_done_callback(_log_abandoned_run)
            raise


def get_prompt_pipeline(request: Request) -> PromptPipeline:
    """FastAPI dependency: the process-wide pipeline built in the lifespan."""
    return request.app.state.prompt_pipeline
