"""Health check endpoints."""

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app import __version__
from app.audit import db

router = APIRouter()

logger = logging.getLogger(__name__)

SERVICE_NAME = "lunablue"


@router.get("/health")
async def get_health() -> dict[str, str]:
    """Report service liveness."""
    return {"service": SERVICE_NAME, "version": __version__, "status": "ok"}


@router.get("/health/ready")
async def get_readiness(request: Request) -> JSONResponse:
    """Report readiness: verifies database connectivity with a trivial query
    and that the LLM model is loaded. Returns 503 (without crashing) when
    either dependency is unavailable. Deliberately lock-free on the LLM side
    so it answers promptly while a generation is in progress."""
    body = {"service": SERVICE_NAME, "version": __version__}

    runtime = getattr(request.app.state, "llm_runtime", None)
    if runtime is not None and runtime.loaded:
        body["model"] = runtime.model_info["model_id"]
        model_ok = True
    else:
        body["model"] = "not_loaded"
        model_ok = False

    try:
        async with db.get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        body["database"] = "ok"
    except Exception:  # pragma: no cover - depends on external Postgres
        logger.warning("Readiness check failed: database unreachable", exc_info=True)
        body["database"] = "unreachable"
        return JSONResponse(
            status_code=503, content={**body, "status": "unavailable"}
        )

    if not model_ok:
        return JSONResponse(
            status_code=503, content={**body, "status": "unavailable"}
        )
    return JSONResponse(content={**body, "status": "ok"})
