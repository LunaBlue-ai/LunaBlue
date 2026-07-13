"""Graph node: final response synthesis.

Produces the answer via the injected :class:`~app.llm.runtime.LlamaRuntime`
using the engineered prompt/system built upstream, and sets both the draft
and the final output. Until a later step adds post-generation refinement,
the two are identical — keeping both fields explicit preserves the audit
contract (``llm_output`` vs ``final_output``).
"""

import time
from typing import Any

from app.llm.runtime import LlamaRuntime


async def synthesize_response(
    state: dict[str, Any], *, llm_runtime: LlamaRuntime
) -> dict[str, Any]:
    """Generate the answer and record synthesis metadata."""
    started = time.perf_counter()
    result = await llm_runtime.generate(
        state["engineered_prompt"], system=state["engineered_system"]
    )
    duration_ms = (time.perf_counter() - started) * 1000
    return {
        "draft_output": result.text,
        "final_output": result.text,
        "model_id": result.model_id,
        "usage": result.usage(),
        "decisions": [
            {
                "node": "respond",
                "model_id": result.model_id,
                "usage": result.usage(),
                "finish_reason": result.finish_reason,
                "duration_ms": duration_ms,
            }
        ],
    }
