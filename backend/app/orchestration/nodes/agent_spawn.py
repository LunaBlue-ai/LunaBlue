"""Graph node: spawn a background agent when the review asks for one (Step 14).

Reached only via the conditional edge in ``graph.py`` (when
``state["review"]["needs_background_work"]`` is true). Builds an
:class:`~app.orchestration.agents.base.AgentSpec` for the reviewed prompt and
hands it to the injected :class:`~app.orchestration.runner.AgentRunner` —
fire-and-forget, so response latency never regresses. The agent id lands in
the graph state (``spawned_agent_id``, mentioned by the respond node) and in
the decision metadata the audit trail persists.

A spawn failure is deliberately non-fatal: background work is best-effort
extra value, so the run proceeds to respond without an agent rather than
failing a prompt the model can already answer.
"""

import logging
import time
from typing import Any

from app.orchestration.agents.base import AgentSpec
from app.orchestration.runner import AgentRunner

logger = logging.getLogger(__name__)

_AGENT_KIND = "research"


async def spawn_background_agent(
    state: dict[str, Any], *, runner: AgentRunner
) -> dict[str, Any]:
    """Spawn the background agent the review called for."""
    started = time.perf_counter()
    review = state.get("review") or {}
    spec = AgentSpec(
        kind=_AGENT_KIND,
        task=state["reviewed_prompt"],
        request_id=state["request_id"],
        session_id=state["session_id"],
    )
    decision: dict[str, Any] = {
        "node": "agent_spawn",
        "kind": _AGENT_KIND,
        "intent": review.get("intent"),
    }
    update: dict[str, Any] = {}
    try:
        agent_id = await runner.spawn(spec)
    except Exception as exc:
        logger.error(
            "Request %s: agent spawn failed: %s", state["request_id"], exc,
            exc_info=True,
        )
        decision["outcome"] = "spawn_failed"
        decision["error"] = f"{type(exc).__name__}: {exc}"
    else:
        update["spawned_agent_id"] = agent_id
        decision["outcome"] = "spawned"
        decision["agent_id"] = agent_id
    decision["duration_ms"] = (time.perf_counter() - started) * 1000
    update["decisions"] = [decision]
    return update
