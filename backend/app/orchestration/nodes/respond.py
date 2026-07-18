"""Graph node: final response synthesis.

Produces the answer via the injected :class:`~app.llm.runtime.LlamaRuntime`
using the engineered prompt/system built upstream, and sets both the draft
and the final output. Step 14: when the run spawned a background agent, the
final output additionally names the agent id so the user knows work is
continuing — the one case where draft (``llm_output``) and final output
differ in the audit record.
"""

import time
from typing import Any

from app.llm.runtime import LlamaRuntime


def _agent_notice(agent_id: str) -> str:
    return (
        f"\n\n---\nBackground agent `{agent_id}` was started to continue "
        "working on this; its progress and result are available from the "
        "agent status APIs."
    )


async def synthesize_response(
    state: dict[str, Any], *, llm_runtime: LlamaRuntime
) -> dict[str, Any]:
    """Generate the answer and record synthesis metadata."""
    started = time.perf_counter()
    result = await llm_runtime.generate(
        state["engineered_prompt"], system=state["engineered_system"]
    )
    duration_ms = (time.perf_counter() - started) * 1000
    agent_id = state.get("spawned_agent_id")
    final_output = result.text
    if agent_id:
        final_output += _agent_notice(agent_id)
    return {
        "draft_output": result.text,
        "final_output": final_output,
        "model_id": result.model_id,
        "usage": result.usage(),
        "decisions": [
            {
                "node": "respond",
                "model_id": result.model_id,
                "usage": result.usage(),
                "finish_reason": result.finish_reason,
                "mentioned_agent_id": agent_id,
                "duration_ms": duration_ms,
            }
        ],
    }
