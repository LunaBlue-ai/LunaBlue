"""Graph node: LLM prompt enhancement plus rolling-summary injection.

The closed-loop prompt-processing stage: the local LLM rewrites the
engineered prompt into a clearer, more complete form (instructions in
``app/llm/prompts/enhance.md``), and the session's rolling chat summary — if
the pipeline injected one into the graph state — is appended under a
``### Chat Summary`` heading *after* the enhancement call, so the enhancer
never sees (and can never rewrite) the summary block.

Both artifacts are internal: the enhanced prompt flows onward as
``engineered_prompt`` and lands in the audit trail via the decision record,
but is never returned to the user. Enhancement failure never fails the run —
the node falls back to the unenhanced prompt and records the failure.
"""

import logging
import time
from typing import Any

from app.llm.runtime import LlamaRuntime, load_system_prompt

logger = logging.getLogger(__name__)

_TEMPLATE_NAME = "enhance"
_SUMMARY_HEADING = "### Chat Summary"

# Enhancement is a rewrite, not creative generation: near-deterministic, with
# the token budget supplied by the caller (PROMPT_ENHANCEMENT_MAX_TOKENS).
_ENHANCE_PARAMS: dict[str, Any] = {"temperature": 0.2}

# Cap on the enhanced-prompt text copied into the decision record (decisions
# land in the prompt_responses.usage JSONB column).
_DECISION_TEXT_MAX_CHARS = 4000


async def enhance_prompt(
    state: dict[str, Any],
    *,
    llm_runtime: LlamaRuntime,
    enabled: bool = True,
    max_tokens: int = 512,
) -> dict[str, Any]:
    """Rewrite the engineered prompt via the LLM and inject the chat summary.

    With ``enabled=False`` (enhancement off but session summary on) the node
    is deterministic: no LLM call, just the summary append.
    """
    started = time.perf_counter()
    base = state["engineered_prompt"]
    enhanced = base
    status = "disabled"
    error: str | None = None
    result = None

    if enabled:
        # Instructions go in the user turn, not the system role — the small
        # local models this runs on answer system-role instructions instead
        # of following them (same finding as llm_review).
        instructions = load_system_prompt(_TEMPLATE_NAME)
        try:
            result = await llm_runtime.generate(
                f"{instructions}\n\nUser prompt:\n---\n{base}\n---",
                max_tokens=max_tokens,
                **_ENHANCE_PARAMS,
            )
            text = result.text.strip()
            if text:
                enhanced = text
                status = "enhanced"
            else:
                status = "fallback"
                error = "empty enhancement output"
        except Exception as exc:
            # Enhancement must never fail the run: fall back to the
            # unenhanced prompt and record what happened.
            status = "fallback"
            error = f"{type(exc).__name__}: {exc}"
            result = None
        if error is not None:
            logger.warning(
                "Request %s: prompt enhancement failed (%s); continuing with "
                "the reviewed prompt unchanged.",
                state.get("request_id"),
                error,
            )

    chat_summary = state.get("chat_summary") or ""
    if chat_summary:
        # Appended after the enhancement call so the enhancer never sees the
        # summary block.
        enhanced = f"{enhanced}\n\n{_SUMMARY_HEADING}\n{chat_summary}"

    duration_ms = (time.perf_counter() - started) * 1000
    decision: dict[str, Any] = {
        "node": "prompt_enhancement",
        "template": _TEMPLATE_NAME if enabled else None,
        "status": status,
        "error": error,
        "enhanced_prompt": enhanced[:_DECISION_TEXT_MAX_CHARS],
        "summary_injected": bool(chat_summary),
        "chat_summary_chars": len(chat_summary),
        "duration_ms": duration_ms,
    }
    if result is not None:
        decision["model_id"] = result.model_id
        decision["usage"] = result.usage()
    return {
        "engineered_prompt": enhanced,
        "enhanced_prompt": enhanced,
        "decisions": [decision],
    }
