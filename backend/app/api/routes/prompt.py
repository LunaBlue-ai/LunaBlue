"""Prompt submission endpoint.

Routing only (per docs/Components/API.md): validate, delegate, respond. The
governance → LLM → audit sequence lives in
:class:`~app.orchestration.pipeline.PromptPipeline`; this handler just maps
its outcomes onto the stable Step 5 wire contract. Step 9 swaps the pipeline
internals for LangGraph execution without touching this module.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from app.api.schemas.prompt import PromptRequest, PromptResponse
from app.governance.intake import PromptRejectedError
from app.orchestration.pipeline import (
    GenerationFailedError,
    PromptPipeline,
    get_prompt_pipeline,
)

router = APIRouter()

# Client-facing text for failed generations. The real error summary is in the
# audit log, never in the response — it may carry internals.
_FAILED_RESPONSE_TEXT = (
    "LunaBlue could not generate a response for this request. "
    "The failure has been recorded; please try again."
)


@router.post(
    "/prompt",
    response_model=PromptResponse,
    summary="Submit a prompt",
    description=(
        "Accepts a prompt, assigns it a UUID request id, runs governance "
        "intake (normalization, policy tagging), generates a response with "
        "the local LLM, records the full request/response chain in the audit "
        "log, and returns the generated text. If no `session_id` is supplied "
        "a new session is created and its id returned. Invalid prompts "
        "(empty, whitespace-only, or over the size limit) are rejected with "
        "422 and are not audited. Prompts rejected by governance policy "
        "return 400 with the reason and are audited with a rejected "
        "governance flag. If generation fails or times out, the response is "
        "a 500 with `status=\"failed\"` and the failure is audited."
    ),
    responses={
        400: {"description": "Rejected by governance policy; detail carries the reason."},
        422: {"description": "Validation error: empty or oversized prompt."},
        500: {
            "model": PromptResponse,
            "description": (
                "Generation failed or timed out; body carries "
                '`status="failed"`.'
            ),
        },
    },
)
async def submit_prompt(
    payload: PromptRequest,
    pipeline: Annotated[PromptPipeline, Depends(get_prompt_pipeline)],
) -> PromptResponse:
    try:
        result = await pipeline.run(
            payload.text,
            session_id=payload.session_id,
            user_id=payload.user_id,
            metadata=payload.metadata,
        )
    except PromptRejectedError as exc:
        raise HTTPException(status_code=400, detail=exc.reason) from exc
    except GenerationFailedError as exc:
        failed = PromptResponse(
            request_id=exc.request_id,
            session_id=exc.session_id,
            status="failed",
            response_text=_FAILED_RESPONSE_TEXT,
            created_at=exc.created_at,
        )
        return JSONResponse(status_code=500, content=failed.model_dump(mode="json"))

    return PromptResponse(
        request_id=result.request_id,
        session_id=result.session_id,
        status="completed",
        response_text=result.response_text,
        created_at=result.created_at,
    )
