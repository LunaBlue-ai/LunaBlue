"""Application factory for the LunaBlue backend."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.api.routes import api_router
from app.audit import db
from app.audit.service import AuditService
from app.config import get_settings
from app.governance.intake import PromptIntake
from app.governance.policy import PolicyEngine
from app.llm.runtime import LlamaRuntime, ModelNotFoundError

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup/shutdown hooks. Later steps add the state store here."""
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger.info(
        "LunaBlue backend %s starting (host=%s, port=%s)",
        __version__,
        settings.host,
        settings.port,
    )
    db.init_engine(settings.database_url)
    audit_service = AuditService()
    audit_service.start()
    app.state.audit_service = audit_service
    app.state.prompt_intake = PromptIntake(
        PolicyEngine(strict_mode=settings.governance_strict_mode),
        max_length=settings.governance_max_prompt_length,
    )
    # The single global LLM runtime (docs/Architecture.md). Loading is
    # deliberately fail-fast: a missing model file aborts startup with an
    # actionable message rather than serving a half-alive process.
    runtime = LlamaRuntime(
        model_path=str(settings.resolved_model_path),
        context_size=settings.llm_context_size,
        gpu_layers=settings.llm_gpu_layers,
        max_tokens=settings.llm_max_tokens,
        temperature=settings.llm_temperature,
    )
    try:
        runtime.load()
    except ModelNotFoundError as exc:
        logger.error("%s", exc)
        # Tear down what startup already built; the finally below never runs
        # when startup itself raises.
        await audit_service.close()
        await db.dispose_engine()
        raise
    app.state.llm_runtime = runtime
    try:
        yield
    finally:
        # Drain queued audit events before tearing down the engine they
        # write through.
        await audit_service.close()
        runtime.close()
        await db.dispose_engine()
        logger.info("LunaBlue backend shutting down")


def create_app() -> FastAPI:
    """Build a fresh application instance (tests create isolated copies)."""
    app = FastAPI(title="LunaBlue", version=__version__, lifespan=lifespan)
    app.include_router(api_router, prefix="/api")
    return app


app = create_app()
