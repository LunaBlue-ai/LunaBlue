"""Application factory for the LunaBlue backend."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.api.routes import api_router
from app.config import get_settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup/shutdown hooks. Later steps add the DB engine, the LLM
    runtime, and the state store here."""
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
    yield
    logger.info("LunaBlue backend shutting down")


def create_app() -> FastAPI:
    """Build a fresh application instance (tests create isolated copies)."""
    app = FastAPI(title="LunaBlue", version=__version__, lifespan=lifespan)
    app.include_router(api_router, prefix="/api")
    return app


app = create_app()
