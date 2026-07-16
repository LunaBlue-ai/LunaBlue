"""Agent status endpoints (Step 15).

Listing is a read-only view over the in-memory
:class:`~app.state.store.StateStore` agent registry, exactly like the run
endpoints in ``routes/state.py``. The detail endpoint is two-tier by design:

- a live agent's summary comes from the store, enriched with its task,
  parameters, and recent lifecycle events from the ``agent_events`` audit
  record (the store never carries those);
- an agent already evicted from live state is *reconstructed* entirely from
  ``agent_events`` — the audit trail is the durable record
  (docs/Components/AUDIT.md), and this endpoint deliberately exercises that
  design instead of returning 404.

``POST /api/agents/{id}/cancel`` exposes
:meth:`~app.orchestration.runner.AgentRunner.cancel`: cancellation is
asynchronous (a running agent settles as ``cancelled`` when its task
unwinds), hence the 202 response.
"""

import logging
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.routes.state import get_state_store
from app.api.schemas.agent import AgentDetail, AgentEventRecord, AgentSummary
from app.audit.service import AgentEvent, AuditService, get_audit_service
from app.orchestration.runner import AgentRunner
from app.state.store import AgentSnapshot, StateStore

logger = logging.getLogger(__name__)

router = APIRouter()

_AGENT_NOT_FOUND = (
    "Unknown agent id: the agent never existed, or it left live state without "
    "leaving an audit trail."
)

AgentStateName = Literal["pending", "running", "completed", "failed", "cancelled"]


def get_agent_runner(request: Request) -> AgentRunner:
    """FastAPI dependency: the process-wide agent runner built in the lifespan."""
    return request.app.state.agent_runner


def _summary_from_snapshot(snapshot: AgentSnapshot) -> AgentSummary:
    return AgentSummary.model_validate(snapshot)


def _event_records(events: list[AgentEvent]) -> list[AgentEventRecord]:
    return [
        AgentEventRecord(
            event_type=event.event_type,
            state=event.state,
            timestamp=event.timestamp,
            payload=event.payload,
        )
        for event in events
    ]


def _spawn_info(events: list[AgentEvent]) -> tuple[str | None, dict[str, Any] | None]:
    """Task description and params from the ``spawned`` audit event, if present."""
    for event in events:
        if event.event_type == "spawned" and event.payload is not None:
            return event.payload.get("task"), event.payload.get("params")
    return None, None


def _reconstruct_detail(events: list[AgentEvent]) -> AgentDetail:
    """Rebuild an evicted agent's detail purely from its audited lifecycle.

    Every field the live registry would have carried is derivable: the
    ``spawned`` payload holds kind/task/session/params, ``progress`` payloads
    hold the last reported phase/fraction, and the terminal event holds the
    result summary or error. Events arrive oldest first.
    """
    task: str | None = None
    params: dict[str, Any] | None = None
    kind = "unknown"
    session_id: str | None = None
    request_id: str | None = None
    state = "pending"
    progress_phase: str | None = None
    progress_fraction: float | None = None
    last_result: str | None = None
    error: str | None = None

    for event in events:
        if event.request_id is not None:
            request_id = event.request_id
        if event.state is not None:
            state = event.state
        payload = event.payload or {}
        if event.event_type == "spawned":
            kind = payload.get("kind", kind)
            task = payload.get("task")
            params = payload.get("params")
            session_id = payload.get("session_id")
        elif event.event_type == "progress":
            progress_phase = payload.get("phase", progress_phase)
            if payload.get("fraction") is not None:
                progress_fraction = payload["fraction"]
        elif event.event_type == "completed":
            last_result = payload.get("summary")
            progress_fraction = 1.0
        elif event.event_type == "failed":
            error = payload.get("error")

    return AgentDetail(
        agent_id=events[0].agent_id,
        kind=kind,
        session_id=session_id,
        request_id=request_id,
        state=state,
        created_at=events[0].timestamp,
        updated_at=events[-1].timestamp,
        progress_phase=progress_phase,
        progress_fraction=progress_fraction,
        last_result=last_result,
        error=error,
        task=task,
        params=params,
        live=False,
        events=_event_records(events),
    )


@router.get(
    "/agents",
    response_model=list[AgentSummary],
    summary="List background agents",
    description=(
        "Status summaries of the background agents in live state, newest "
        "first, optionally filtered by lifecycle state and/or session. "
        "Settled agents evicted from live state are absent here but remain "
        "individually queryable via GET /api/agents/{agent_id}."
    ),
)
async def list_agents(
    store: Annotated[StateStore, Depends(get_state_store)],
    state: Annotated[
        AgentStateName | None,
        Query(description="Only agents currently in this lifecycle state."),
    ] = None,
    session_id: Annotated[
        str | None, Query(description="Only agents spawned under this session.")
    ] = None,
    limit: Annotated[
        int, Query(ge=1, le=500, description="Maximum agents to return.")
    ] = 100,
) -> list[AgentSummary]:
    # The registry iterates in registration order; walking it reversed makes
    # the stable sort resolve created_at ties (same clock tick) newest-first.
    agents = [
        snapshot
        for snapshot in reversed(store.list_agents())
        if (state is None or snapshot.state == state)
        and (session_id is None or snapshot.session_id == session_id)
    ]
    agents.sort(key=lambda snapshot: snapshot.created_at, reverse=True)
    return [_summary_from_snapshot(snapshot) for snapshot in agents[:limit]]


@router.get(
    "/agents/{agent_id}",
    response_model=AgentDetail,
    summary="Full detail of one background agent",
    description=(
        "The agent's status plus its task, parameters, and recent lifecycle "
        "events. Live agents are served from the in-memory registry enriched "
        "with their agent_events audit trail; agents already evicted from "
        "live state are reconstructed entirely from that trail (live=false). "
        "404 only when no trace of the agent exists anywhere."
    ),
    responses={
        404: {"description": "Agent unknown in live state and audit."},
        503: {
            "description": (
                "Agent not in live state and the audit record is unreachable."
            )
        },
    },
)
async def get_agent_detail(
    agent_id: str,
    store: Annotated[StateStore, Depends(get_state_store)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
) -> AgentDetail:
    snapshot = store.get_agent(agent_id)
    if snapshot is None:
        try:
            events = await audit.fetch_agent_events(agent_id)
        except Exception as exc:
            # Don't claim "not found" when the durable record is merely
            # unreachable (e.g. Postgres down).
            logger.exception("agent_events lookup failed for %s", agent_id)
            raise HTTPException(
                status_code=503,
                detail=(
                    "Agent is not in live state and the audit record is "
                    "currently unreachable."
                ),
            ) from exc
        if not events:
            raise HTTPException(status_code=404, detail=_AGENT_NOT_FOUND)
        return _reconstruct_detail(events)

    # Live agent: the audit trail supplies what the store never carries. A
    # failing audit read degrades the enrichment, never the status itself.
    try:
        events = await audit.fetch_agent_events(agent_id)
    except Exception:
        logger.exception("agent_events lookup failed for live agent %s", agent_id)
        events = []
    task, params = _spawn_info(events)
    if task is None and snapshot.queued_tasks:
        task = snapshot.queued_tasks[0].description
    return AgentDetail(
        **_summary_from_snapshot(snapshot).model_dump(),
        task=task,
        params=params,
        live=True,
        events=_event_records(events),
    )


@router.post(
    "/agents/{agent_id}/cancel",
    response_model=AgentSummary,
    status_code=202,
    summary="Cancel a background agent",
    description=(
        "Requests cancellation of a pending or running agent. Cancellation "
        "is asynchronous: a pending agent settles as cancelled immediately, "
        "a running one when its task unwinds — watch agent_updated events or "
        "poll for the terminal state. Returns the agent's status at the time "
        "the request was accepted."
    ),
    responses={
        404: {"description": "Agent unknown in live state."},
        409: {"description": "Agent already settled; nothing to cancel."},
    },
)
async def cancel_agent(
    agent_id: str,
    store: Annotated[StateStore, Depends(get_state_store)],
    runner: Annotated[AgentRunner, Depends(get_agent_runner)],
) -> AgentSummary:
    cancelled = await runner.cancel(agent_id)
    snapshot = store.get_agent(agent_id)
    if not cancelled:
        if snapshot is None:
            raise HTTPException(status_code=404, detail=_AGENT_NOT_FOUND)
        raise HTTPException(
            status_code=409,
            detail=f"Agent already settled as {snapshot.state!r}.",
        )
    if snapshot is None:  # pragma: no cover - settled and evicted mid-request
        raise HTTPException(status_code=404, detail=_AGENT_NOT_FOUND)
    return _summary_from_snapshot(snapshot)
