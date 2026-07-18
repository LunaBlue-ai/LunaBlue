"""Wire format for the live run/session status APIs (Step 10).

These models mirror the immutable snapshots produced by
:mod:`app.state.store` (``from_attributes`` builds them straight from the
frozen dataclasses). They describe *live* state only: evicted runs are gone
from these endpoints while remaining fully present in the audit
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
            "spawning, responding, completed, or failed."
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


class SessionSummary(BaseModel):
    """Session metadata with run ids only — WebSocket ``session_updated``
    payloads (Step 13), where the runs travel as their own events."""

    model_config = ConfigDict(from_attributes=True)

    session_id: str = Field(description="Session identifier.")
    user_id: str | None = Field(description="User the session belongs to, if known.")
    created_at: datetime = Field(description="When the session was first seen (UTC).")
    last_activity_at: datetime = Field(description="Last session activity (UTC).")
    run_ids: list[str] = Field(description="Retained run ids, newest first.")


class SummaryResetResponse(BaseModel):
    """Outcome of a chat-summary reset (Step 20)."""

    session_id: str = Field(description="The session that was targeted.")
    cleared: bool = Field(
        description=(
            "True when a reset was applied to an existing session; false "
            "when the session was unknown (nothing to clear)."
        )
    )


class AgentTaskRecord(BaseModel):
    """One queued unit of background agent work (Step 14)."""

    model_config = ConfigDict(from_attributes=True)

    task_id: str = Field(description="Task identifier.")
    description: str = Field(description="Human-readable task description.")
    enqueued_at: datetime = Field(description="When the task was queued (UTC).")


class AgentStatus(BaseModel):
    """Live status snapshot of one background agent (Step 14); the WebSocket
    ``agent_updated`` payload."""

    model_config = ConfigDict(from_attributes=True)

    agent_id: str = Field(description="Agent identifier.")
    kind: str = Field(description="Registered agent type (e.g. research).")
    session_id: str | None = Field(description="Session the agent serves, if any.")
    request_id: str | None = Field(
        description="Prompt run that spawned the agent, if any."
    )
    state: str = Field(
        description=(
            "Agent lifecycle state: pending, running, completed, failed, "
            "or cancelled."
        )
    )
    created_at: datetime = Field(description="When the agent was created (UTC).")
    updated_at: datetime = Field(description="Last agent state change (UTC).")
    progress_phase: str | None = Field(
        description="Agent-reported phase label while running."
    )
    progress_fraction: float | None = Field(
        description="Agent-reported completion estimate (0.0–1.0), if any."
    )
    last_result: str | None = Field(
        description=(
            "Short result summary once completed (the full payload is in the "
            "agent_events audit record)."
        )
    )
    error: str | None = Field(description="Error summary once failed.")
    queued_tasks: list[AgentTaskRecord] = Field(
        description="Queued work not yet picked up by a worker."
    )
