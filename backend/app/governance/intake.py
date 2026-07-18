"""Prompt intake: normalization, enrichment, and policy review.

:class:`PromptIntake` sits between the API and (future) orchestration. It
normalizes raw prompt text (unicode, whitespace, length bounds), enriches it
with session context and a per-session ``prompt_version``, and runs the
:class:`~app.governance.policy.PolicyEngine` over the normalized form. The
result is a :class:`ReviewedPrompt`; rejected prompts raise
:class:`PromptRejectedError` carrying the same auditable metadata so the
route can record the rejection and return a 4xx.

Everything here is deterministic and in-process — no LLM calls.
"""

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from fastapi import Request

from app.governance.policy import GovernanceMetadata, PolicyEngine

_HORIZONTAL_WS = re.compile(r"[ \t]+")
_EXCESS_BLANK_LINES = re.compile(r"\n{3,}")


def normalize_text(raw: str) -> str:
    """Normalize unicode (NFKC), drop control characters, collapse whitespace.

    Newlines are preserved (runs of blank lines collapse to one blank line) so
    prompt structure such as lists and paragraphs survives review.
    """
    text = unicodedata.normalize("NFKC", raw)
    # Strip control/format characters (zero-width spaces, BOMs, \r) but keep
    # newlines and tabs for the whitespace pass below.
    text = "".join(
        ch for ch in text if ch in "\n\t" or unicodedata.category(ch)[0] != "C"
    )
    lines = [_HORIZONTAL_WS.sub(" ", line).strip() for line in text.split("\n")]
    return _EXCESS_BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()


@dataclass(frozen=True, slots=True)
class IntakeContext:
    """Request context the route hands to :meth:`PromptIntake.review`."""

    session_id: str
    user_id: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class ReviewedPrompt:
    """A prompt that passed intake, ready for orchestration and audit."""

    reviewed_text: str
    prompt_version: str
    governance: GovernanceMetadata
    session_id: str
    user_id: str | None
    reviewed_at: datetime


class PromptRejectedError(Exception):
    """Intake rejected the prompt; carries everything needed to audit it."""

    def __init__(
        self,
        reason: str,
        metadata: GovernanceMetadata,
        *,
        reviewed_text: str | None = None,
        prompt_version: str | None = None,
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.metadata = metadata
        self.reviewed_text = reviewed_text
        self.prompt_version = prompt_version


class PromptIntake:
    """Normalizes, enriches, and policy-reviews incoming prompts."""

    def __init__(self, policy: PolicyEngine, *, max_length: int = 32_000) -> None:
        self._policy = policy
        self._max_length = max_length
        # Per-session resubmission counters. In-memory and per-process by
        # design: prompt_version is a review sequence number, not a durable
        # identifier (the audit database is the durable record).
        self._versions: dict[str, int] = {}

    def review(self, raw_text: str, context: IntakeContext) -> ReviewedPrompt:
        """Return the reviewed prompt or raise :class:`PromptRejectedError`."""
        reviewed_at = datetime.now(timezone.utc)
        version = str(self._next_version(context.session_id))

        text = normalize_text(raw_text)
        if not text:
            reason = "Prompt is empty after normalization."
            raise PromptRejectedError(
                reason, self._structural_rejection(reason), prompt_version=version
            )
        if len(text) > self._max_length:
            reason = (
                f"Prompt exceeds the maximum length of {self._max_length} "
                "characters after normalization."
            )
            raise PromptRejectedError(
                reason,
                self._structural_rejection(reason),
                reviewed_text=text,
                prompt_version=version,
            )

        metadata = self._policy.evaluate(text)
        if metadata.decision == "rejected":
            raise PromptRejectedError(
                metadata.rejection_reason or "Prompt rejected by policy.",
                metadata,
                reviewed_text=text,
                prompt_version=version,
            )

        return ReviewedPrompt(
            reviewed_text=text,
            prompt_version=version,
            governance=metadata,
            session_id=context.session_id,
            user_id=context.user_id,
            reviewed_at=reviewed_at,
        )

    def _next_version(self, session_id: str) -> int:
        nxt = self._versions.get(session_id, 0) + 1
        self._versions[session_id] = nxt
        return nxt

    def _structural_rejection(self, reason: str) -> GovernanceMetadata:
        """Metadata for rejections that apply regardless of strict mode."""
        return GovernanceMetadata(
            decision="rejected",
            tags=("intake:invalid",),
            directives=(),
            rationale=(reason,),
            matched_rules=(),
            strict_mode=self._policy.strict_mode,
            rejection_reason=reason,
        )


def get_prompt_intake(request: Request) -> PromptIntake:
    """FastAPI dependency: the process-wide intake built in the lifespan."""
    return request.app.state.prompt_intake
