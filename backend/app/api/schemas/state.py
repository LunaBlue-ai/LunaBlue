"""Wire format for the live run/session status APIs (Step 10).

These models mirror the immutable snapshots produced by
:mod:`app.state.store` (``from_attributes`` builds them straight from the
frozen dataclasses). They describe *live* state only: evicted runs are gone
from these endpoints while remaining fully present in the Postgres audit
record. Step 13's WebSocket events reuse the same shapes.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PhaseRecord(BaseModel):
    """One timed entry in a run's phase history."""

    model_config = ConfigDict(from_attributes=True)

    phase: str = Field(description="Phase entered.")
    node: str | None = Field(
        description="Graph node that triggered the phase, if any."
    )
    entered_at: datetime = Field(description="When the phase was entered (UTC).")
    duration_ms: float | None = Field(
        description=(
            "Time spent in the phase; null while it is still the current one."
        )
    )


class RunStatus(BaseModel):
    """Full live status snapshot of one prompt run."""

    model_config = ConfigDict(from_attributes=True)

    request_id: str = Field(description="Server-assigned request UUID.")
    session_id: str = Field(description="Session the run belongs to.")
    phase: str = Field(
        description=(
            "Current phase: received, governance, engineering, reviewing, "
            "responding, completed, or failed."
        )
    )
    current_node: str | None = Field(
        description="Graph node currently executing, if the run is inside one."
    )
    created_at: datetime = Field(description="When the run was accepted (UTC).")
    updated_at: datetime = Field(description="Last phase change (UTC).")
    result_summary: str | None = Field(
        description="Short output summary once completed (full text is audited)."
    )
    error: str | None = Field(description="Error summary once failed.")
    phases: list[PhaseRecord] = Field(
        description="Timed phase history, oldest first."
    )


class SessionStatus(BaseModel):
    """Session metadata plus its recent retained runs."""

    session_id: str = Field(description="Session identifier.")
    user_id: str | None = Field(description="User the session belongs to, if known.")
    created_at: datetime = Field(description="When the session was first seen (UTC).")
    last_activity_at: datetime = Field(description="Last session activity (UTC).")
    runs: list[RunStatus] = Field(
        description="Recent retained runs, newest first."
    )
