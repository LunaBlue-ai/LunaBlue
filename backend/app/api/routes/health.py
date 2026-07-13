"""Health check endpoint."""

from fastapi import APIRouter

from app import __version__

router = APIRouter()

SERVICE_NAME = "lunablue"


@router.get("/health")
async def get_health() -> dict[str, str]:
    """Report service liveness."""
    return {"service": SERVICE_NAME, "version": __version__, "status": "ok"}
