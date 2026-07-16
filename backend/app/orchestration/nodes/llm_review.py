"""Graph node: LLM-assisted review/planning pass over the engineered prompt.

Asks the model (via the injected :class:`~app.llm.runtime.LlamaRuntime`) to
classify intent, decide whether background work is warranted, and flag
concerns. The instructions live in ``app/llm/prompts/review.md``. The model's
judgment lands in ``state["review"]`` and the decision metadata.

A generation failure propagates (the pipeline audits it and fails the request
cleanly); an *unparseable* verdict does not — local models produce imperfect
JSON, so that degrades to a conservative default outcome instead.
"""

import json
import re
import time
from typing import Any

from app.llm.runtime import LlamaRuntime, load_system_prompt

_TEMPLATE_NAME = "review"
_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)

# Review is a short structured verdict: deterministic and tightly bounded so
# the extra LLM call adds as little latency as possible.
_REVIEW_PARAMS: dict[str, Any] = {"temperature": 0.0, "max_tokens": 256}


def parse_review_verdict(text: str) -> dict[str, Any]:
    """Extract the review JSON from model output, tolerating surrounding
    prose; fall back to a conservative default when nothing parses."""
    match = _JSON_OBJECT.search(text)
    if match:
        try:
            raw = json.loads(match.group())
        except ValueError:
            raw = None
        if isinstance(raw, dict):
            concerns = raw.get("concerns")
            return {
                "intent": str(raw.get("intent", "unknown")),
                "needs_background_work": bool(
                    raw.get("needs_background_work", False)
                ),
                "concerns": [str(c) for c in concerns]
                if isinstance(concerns, list)
                else [],
                "parsed": True,
            }
    return {
        "intent": "unknown",
        "needs_background_work": False,
        "concerns": ["review output was not parseable"],
        "parsed": False,
        "raw_output": text[:500],
    }


async def review_engineered_prompt(
    state: dict[str, Any], *, llm_runtime: LlamaRuntime
) -> dict[str, Any]:
    """Run the review pass and record its outcome in the graph state."""
    started = time.perf_counter()
    # The instructions go in the user turn, not the system role: the small
    # local models this runs on reliably follow user-turn instructions but
    # answer the prompt instead of reviewing it when they arrive as system
    # text (verified against the default model).
    instructions = load_system_prompt(_TEMPLATE_NAME)
    result = await llm_runtime.generate(
        f"{instructions}\n\nPrompt to review:\n---\n"
        f"{state['engineered_prompt']}\n---",
        **_REVIEW_PARAMS,
    )
    outcome = parse_review_verdict(result.text)
    duration_ms = (time.perf_counter() - started) * 1000
    return {
        "review": outcome,
        "decisions": [
            {
                "node": "llm_review",
                "template": _TEMPLATE_NAME,
                "outcome": outcome,
                "model_id": result.model_id,
                "usage": result.usage(),
                "duration_ms": duration_ms,
            }
        ],
    }
