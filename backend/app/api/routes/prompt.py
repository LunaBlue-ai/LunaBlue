"""Prompt submission endpoint.

Routing only (per docs/Components/API.md): validate, delegate, respond. The
raw text flows through governance intake (``PromptIntake.review``); both the
raw and reviewed prompt plus the governance decision are audited. Steps 7-9
slot the LLM pipeline underneath this handler without changing the contract.
"""

import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.api.schemas.prompt import PromptRequest, PromptResponse
from app.audit.service import AuditService, get_audit_service
from app.governance.intake import (
    IntakeContext,
    PromptIntake,
    PromptRejectedError,
    get_prompt_intake,
)

router = APIRouter()

# Stub marker prepended to every response until the LLM pipeline exists
# (Step 7). Only response_text changes when the real pipeline lands.
_STUB_PREFIX = "[stub] LunaBlue received your prompt: "


@router.post(
    "/prompt",
    response_model=PromptResponse,
    summary="Submit a prompt",
    description=(
        "Accepts a prompt, assigns it a UUID request id, runs governance "
        "intake (normalization, policy tagging), records it in the audit "
        "log, and returns a response. If no `session_id` is supplied a new "
        "session is created and its id returned. The response text is "
        "currently a canned stub echoing the reviewed prompt; the shape of "
        "this contract is stable and will not change when the real LLM "
        "pipeline replaces the stub. Invalid prompts (empty, whitespace-only, "
        "or over the size limit) are rejected with 422 and are not audited. "
        "Prompts rejected by governance policy return 400 with the reason "
        "and are audited with a rejected governance flag."
    ),
    responses={
        400: {"description": "Rejected by governance policy; detail carries the reason."},
        422: {"description": "Validation error: empty or oversized prompt."},
    },
)
async def submit_prompt(
    payload: PromptRequest,
    audit: Annotated[AuditService, Depends(get_audit_service)],
    intake: Annotated[PromptIntake, Depends(get_prompt_intake)],
) -> PromptResponse:
    request_id = str(uuid.uuid4())
    session_id = payload.session_id or str(uuid.uuid4())

    # SessionEvent upserts, so emitting unconditionally both creates new
    # sessions and touches existing ones — and, because audit events are
    # written in order, guarantees the session row exists before the
    # prompt_requests FK references it.
    audit.record_session(
        session_id, user_id=payload.user_id, metadata=payload.metadata
    )

    context = IntakeContext(
        session_id=session_id, user_id=payload.user_id, metadata=payload.metadata
    )
    try:
        reviewed = intake.review(payload.text, context)
    except PromptRejectedError as exc:
        # Rejections are audited too: raw text untouched, plus whatever the
        # intake produced before rejecting (normalized text, version) and the
        # governance metadata carrying the rejected decision.
        audit.record_prompt_request(
            request_id,
            payload.text,
            session_id=session_id,
            user_id=payload.user_id,
            reviewed_prompt=exc.reviewed_text,
            prompt_version=exc.prompt_version,
            governance=exc.metadata.to_dict(),
        )
        raise HTTPException(status_code=400, detail=exc.reason) from exc

    audit.record_prompt_request(
        request_id,
        payload.text,
        session_id=session_id,
        user_id=payload.user_id,
        reviewed_prompt=reviewed.reviewed_text,
        prompt_version=reviewed.prompt_version,
        governance=reviewed.governance.to_dict(),
    )

    return PromptResponse(
        request_id=request_id,
        session_id=session_id,
        status="completed",
        response_text=_STUB_PREFIX + reviewed.reviewed_text,
        created_at=datetime.now(timezone.utc),
    )
