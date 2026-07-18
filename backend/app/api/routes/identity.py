"""Identity endpoints (Step 20).

The five identity fields are user-facing settings (unlike the chat summary,
which stays internal): defaults come from the ``IDENTITY_*`` settings, and a
PUT replaces the in-memory values for the rest of the process lifetime. The
pipeline pins the resulting block into every injected chat summary while the
session summary feature is enabled.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.api.schemas.identity import Identity
from app.state.identity import IdentityStore

router = APIRouter()


def get_identity_store(request: Request) -> IdentityStore:
    """FastAPI dependency: the process-wide identity store from the lifespan."""
    return request.app.state.identity


@router.get(
    "/identity",
    response_model=Identity,
    summary="Current identity fields",
    description=(
        "The five identity fields pinned into every injected chat summary. "
        "Defaults come from the IDENTITY_* settings; runtime edits are "
        "in-memory and lost on restart."
    ),
)
async def get_identity(
    store: Annotated[IdentityStore, Depends(get_identity_store)],
) -> Identity:
    return Identity(**store.get())


@router.put(
    "/identity",
    response_model=Identity,
    summary="Replace the identity fields",
    description=(
        "Full replace: omitted fields become empty. Values are "
        "whitespace-stripped; each field is capped at 200 characters. The "
        "change takes effect on the next prompt and survives summary resets "
        "(identity is stored outside the rolling summary buffer)."
    ),
)
async def put_identity(
    body: Identity,
    store: Annotated[IdentityStore, Depends(get_identity_store)],
) -> Identity:
    return Identity(**store.replace(body.model_dump()))
