"""Health check endpoints.

Liveness vs. readiness (Step 17):

- ``GET /api/health`` — liveness: the process is up and the event loop
  answers. Never touches dependencies, so it responds promptly even while a
  generation is in flight or Postgres is down.
- ``GET /api/health/ready`` — readiness: every dependency is examined and
  reported individually under ``checks`` (database reachable, model loaded
  *and* healthy, audit queue not overflowing, agent runner alive). 503 with
  the same body shape when any check fails, so the StatusBar can show which
  dependency degraded. The legacy top-level ``model``/``database`` fields are
  kept for pre-Step-17 consumers.
"""

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app import __version__
from app.audit import db

router = APIRouter()

logger = logging.getLogger(__name__)

SERVICE_NAME = "lunablue"

# Readiness must answer fast even when Postgres is black-holing packets.
_DB_CHECK_TIMEOUT_SECONDS = 5.0


@router.get("/health")
async def get_health() -> dict[str, str]:
    """Report service liveness."""
    return {"service": SERVICE_NAME, "version": __version__, "status": "ok"}


def _check_model(request: Request) -> tuple[dict[str, Any], str]:
    """The model check plus the legacy top-level ``model`` field value."""
    runtime = getattr(request.app.state, "llm_runtime", None)
    if runtime is None or not runtime.loaded:
        return {"ok": False, "detail": "not_loaded"}, "not_loaded"
    info = runtime.model_info
    model_id = info["model_id"]
    # True/False from the startup probe; None when unknown (test fakes).
    offload = info["gpu_offload_supported"]
    if not runtime.healthy:
        return (
            {
                "ok": False,
                "detail": "unhealthy",
                "model_id": model_id,
                "gpu_offload_supported": offload,
                # last_error is an exception summary, not a stack trace or
                # path; full details are in the logs.
                "error": runtime.last_error,
            },
            model_id,
        )
    return (
        {
            "ok": True,
            "detail": "loaded",
            "model_id": model_id,
            "gpu_offload_supported": offload,
        },
        model_id,
    )


async def _check_database() -> dict[str, Any]:
    try:
        async with asyncio.timeout(_DB_CHECK_TIMEOUT_SECONDS):
            async with db.get_engine().connect() as conn:
                await conn.execute(text("SELECT 1"))
        return {"ok": True, "detail": "ok"}
    except Exception:
        logger.warning(
            "Readiness check failed: database unreachable", exc_info=True
        )
        return {"ok": False, "detail": "unreachable"}


def _check_audit_queue(request: Request) -> dict[str, Any]:
    audit = getattr(request.app.state, "audit_service", None)
    if audit is None:
        return {"ok": False, "detail": "not_started"}
    return {
        "ok": not audit.saturated,
        "detail": "overflowing" if audit.saturated else "ok",
        "depth": audit.queue_depth,
        "capacity": audit.queue_capacity,
        "dropped_total": audit.dropped_total,
    }


def _check_agent_runner(request: Request) -> dict[str, Any]:
    runner = getattr(request.app.state, "agent_runner", None)
    if runner is None:
        return {"ok": False, "detail": "not_started"}
    return {"ok": runner.alive, "detail": "ok" if runner.alive else "stopped"}


@router.get("/health/ready")
async def get_readiness(request: Request) -> JSONResponse:
    """Report readiness with per-dependency detail (see module docstring).

    Deliberately lock-free on the LLM side so it answers promptly while a
    generation is in progress, and time-bounded on the database side so a
    hanging Postgres yields a fast 503 rather than a stalled probe.
    """
    model_check, model_field = _check_model(request)
    checks: dict[str, dict[str, Any]] = {
        "model": model_check,
        "database": await _check_database(),
        "audit_queue": _check_audit_queue(request),
        "agent_runner": _check_agent_runner(request),
    }
    ready = all(check["ok"] for check in checks.values())
    body = {
        "service": SERVICE_NAME,
        "version": __version__,
        "status": "ok" if ready else "unavailable",
        # Legacy fields, pre-dating the structured checks.
        "model": model_field,
        "database": checks["database"]["detail"],
        "checks": checks,
    }
    return JSONResponse(status_code=200 if ready else 503, content=body)
