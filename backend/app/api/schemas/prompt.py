"""Public request/response contract for the prompt API.

These models are the stable wire format for ``POST /api/prompt``: the
frontend (Step 11) mirrors them in TypeScript, and Steps 6-9 change only how
``response_text`` is produced, never this shape.

Validation policy: malformed input (empty, whitespace-only, or oversized
prompts; overlong ids) is rejected with 422 *before* the route handler runs,
so rejected requests write no audit rows.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

# Hard cap on prompt size. Oversized prompts are rejected, not truncated.
MAX_PROMPT_LENGTH = 32_000

# Matches the String(64) id columns in the audit schema.
_ID_MAX_LENGTH = 64


class PromptRequest(BaseModel):
    """A prompt submitted by a client."""

    text: str = Field(
        min_length=1,
        max_length=MAX_PROMPT_LENGTH,
        description=(
            "The prompt text. Must be non-empty (not just whitespace) and at "
            f"most {MAX_PROMPT_LENGTH} characters; oversized prompts are "
            "rejected, not truncated."
        ),
    )
    session_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=_ID_MAX_LENGTH,
        description=(
            "Existing session to attach this request to. Omit to have the "
            "server create a new session and return its id."
        ),
    )
    user_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=_ID_MAX_LENGTH,
        description="Identifier of the submitting user, if known.",
    )
    metadata: dict[str, Any] | None = Field(
        default=None,
        description="Arbitrary client context, stored on the session record.",
    )

    @field_validator("text")
    @classmethod
    def text_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must contain non-whitespace characters")
        return value


class PromptResponse(BaseModel):
    """The outcome of a prompt submission."""

    request_id: str = Field(
        description="Server-assigned UUID identifying this request."
    )
    session_id: str = Field(
        description=(
            "Session the request was recorded under: the one supplied in the "
            "request, or a newly created one."
        )
    )
    status: Literal["completed", "failed"] = Field(
        description="Terminal status of the request."
    )
    response_text: str = Field(
        description=(
            "The assistant output. Stubbed until the LLM pipeline lands "
            "(Step 7+)."
        )
    )
    created_at: datetime = Field(
        description="Server timestamp (UTC) when the request was accepted."
    )
