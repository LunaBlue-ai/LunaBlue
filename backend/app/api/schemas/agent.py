"""Wire format for the agent status APIs (Step 15).

:class:`AgentSummary` mirrors the live :class:`~app.state.store.AgentSnapshot`
(``from_attributes`` builds it straight from the frozen dataclass) and is the
same field set the WebSocket ``agent_updated`` payload carries (minus the
queued-task list), so polling ``GET /api/agents`` and consuming live events
are interchangeable on the frontend.

:class:`AgentDetail` adds what only the ``agent_events`` audit record knows:
the task description and parameters (persisted on the ``spawned`` event) and
the recent lifecycle events. For agents already evicted from live state the
whole detail is reconstructed from those events (api/routes/agents.py).
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AgentSummary(BaseModel):
    """Live status summary of one background agent."""

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


class AgentEventRecord(BaseModel):
    """One ``agent_events`` audit entry, as served by the detail endpoint."""

    event_type: str = Field(
        description=(
            "Lifecycle event type: spawned, started, progress, completed, "
            "failed, cancelled, or an agent-specific event."
        )
    )
    state: str | None = Field(
        description="Agent lifecycle state at emission time, if recorded."
    )
    timestamp: datetime = Field(description="When the event was emitted (UTC).")
    payload: dict[str, Any] | None = Field(
        description="Event-specific payload (task, progress, result, error…)."
    )


class AgentDetail(AgentSummary):
    """Full agent detail: the live summary plus its audited history."""

    task: str | None = Field(
        description="Task description the agent was spawned with."
    )
    params: dict[str, Any] | None = Field(
        description="Kind-specific parameters the agent was spawned with."
    )
    live: bool = Field(
        description=(
            "True when the summary came from the live registry; false when "
            "the agent was evicted and reconstructed from agent_events."
        )
    )
    events: list[AgentEventRecord] = Field(
        description="Recent lifecycle events, oldest first."
    )
