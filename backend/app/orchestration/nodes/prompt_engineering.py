"""Graph node: transform the reviewed prompt into the engineered generation
input.

Selects the ``system`` template from ``app/llm/prompts/``, appends the
governance safety directives carried in the graph state, and records what it
did in the accumulated decision metadata. Deterministic — no LLM call.
"""

import time
from typing import Any

from app.llm.runtime import load_system_prompt

_TEMPLATE_NAME = "system"


def engineer_prompt(state: dict[str, Any]) -> dict[str, Any]:
    """Produce ``engineered_prompt``/``engineered_system`` from the reviewed
    prompt and governance metadata."""
    started = time.perf_counter()
    governance = state["governance"]
    system = load_system_prompt(_TEMPLATE_NAME)
    directives = list(governance.directives)
    if directives:
        lines = "\n".join(f"- {d}" for d in directives)
        system = (
            f"{system}\n\nApply these governance directives to your response:"
            f"\n{lines}"
        )
    # The user-facing generation input is the reviewed prompt unchanged; the
    # engineering happens in the system side. Later steps may rewrite it.
    engineered = state["reviewed_prompt"]
    duration_ms = (time.perf_counter() - started) * 1000
    return {
        "engineered_prompt": engineered,
        "engineered_system": system,
        "decisions": [
            {
                "node": "prompt_engineering",
                "template": _TEMPLATE_NAME,
                "directives_applied": directives,
                "engineered_prompt_chars": len(engineered),
                "summary": (
                    f"Filled the '{_TEMPLATE_NAME}' template with "
                    f"{len(directives)} governance directive(s); user prompt "
                    "passed through unchanged."
                ),
                "duration_ms": duration_ms,
            }
        ],
    }
