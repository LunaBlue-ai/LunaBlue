"""Live run/session status endpoints (Step 10).

Read-only views over the in-memory :class:`~app.state.store.StateStore`:
routing only — snapshots come straight from the store, so polling here never
contends with graph execution. Evicted (old) runs 404 here while remaining
fully present in the Postgres audit record; Step 13 adds WebSocket streaming
of the same state.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.schemas.state import RunStatus, SessionStatus
from app.state.store import StateStore

router = APIRouter()

_RUN_NOT_FOUND = (
    "Unknown request id: the run never existed or has been evicted from live "
    "state. The audit log holds the durable record."
)
_SESSION_NOT_FOUND = "Unknown session id."


def get_state_store(request: Request) -> StateStore:
    """FastAPI dependency: the process-wide state store built in the lifespan."""
    return request.app.state.state_store


@router.get(
    "/runs/{request_id}",
    response_model=RunStatus,
    summary="Live status of one prompt run",
    description=(
        "Full status snapshot of an in-flight or recently finished prompt "
        "run: current phase, executing node, timed phase history, and the "
        "result or error summary once terminal. Runs evicted from live "
        "state return 404; their durable record lives in the audit log."
    ),
    responses={404: {"description": "Run unknown or evicted from live state."}},
)
async def get_run_status(
    request_id: str,
    store: Annotated[StateStore, Depends(get_state_store)],
) -> RunStatus:
    snapshot = store.get_run(request_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=_RUN_NOT_FOUND)
    return RunStatus.model_validate(snapshot)


@router.get(
    "/sessions/{session_id}",
    response_model=SessionStatus,
    summary="Session metadata and its recent runs",
    description=(
        "Session metadata (user, created, last activity) plus status "
        "snapshots of its most recent retained runs, newest first."
    ),
    responses={404: {"description": "Session unknown."}},
)
async def get_session_status(
    session_id: str,
    store: Annotated[StateStore, Depends(get_state_store)],
    limit: Annotated[
        int, Query(ge=1, le=100, description="Maximum runs to return.")
    ] = 20,
) -> SessionStatus:
    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=_SESSION_NOT_FOUND)
    return SessionStatus(
        session_id=session.session_id,
        user_id=session.user_id,
        created_at=session.created_at,
        last_activity_at=session.last_activity_at,
        runs=[
            RunStatus.model_validate(run)
            for run in store.session_runs(session_id, limit=limit)
        ],
    )
