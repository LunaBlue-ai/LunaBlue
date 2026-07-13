"""TEMPORARY debug endpoint (Step 7).

``POST /api/debug/generate`` calls the LLM runtime directly, bypassing
governance intake and the audit log. It exists only to verify the model
bring-up (Step 7 verification) and will be removed when Step 9 wires the
real prompt pipeline. Do not build on it.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.llm.runtime import LlamaRuntime, get_llm_runtime, load_system_prompt

router = APIRouter()


class DebugGenerateRequest(BaseModel):
    prompt: str = Field(min_length=1)
    system: str | None = Field(
        default=None,
        description="System prompt override; defaults to prompts/system.md.",
    )
    max_tokens: int | None = Field(default=None, ge=1)
    temperature: float | None = Field(default=None, ge=0.0)


class DebugGenerateResponse(BaseModel):
    text: str
    model_id: str
    usage: dict[str, Any]


@router.post(
    "/debug/generate",
    response_model=DebugGenerateResponse,
    summary="[TEMPORARY] Direct model generation",
    description=(
        "Runs a raw generate() against the local model, bypassing governance "
        "and audit. Step 7 bring-up verification only; removed in Step 9."
    ),
)
async def debug_generate(
    payload: DebugGenerateRequest,
    runtime: Annotated[LlamaRuntime, Depends(get_llm_runtime)],
) -> DebugGenerateResponse:
    overrides = {
        k: v
        for k, v in (
            ("max_tokens", payload.max_tokens),
            ("temperature", payload.temperature),
        )
        if v is not None
    }
    result = await runtime.generate(
        payload.prompt,
        system=payload.system if payload.system is not None else load_system_prompt(),
        **overrides,
    )
    return DebugGenerateResponse(
        text=result.text, model_id=result.model_id, usage=result.usage()
    )
