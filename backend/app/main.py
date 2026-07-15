"""Application factory for the LunaBlue backend."""

import logging
import mimetypes
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response

from app import __version__
from app.api import websocket
from app.api.routes import api_router
from app.audit import db
from app.audit.service import AuditService
from app.config import get_settings
from app.governance.intake import PromptIntake
from app.governance.policy import PolicyEngine
from app.llm.runtime import LlamaRuntime, ModelNotFoundError
from app.orchestration.pipeline import PromptPipeline
from app.orchestration.runner import AgentRunner
from app.state.events import EventBus
from app.state.store import StateStore

logger = logging.getLogger(__name__)

# Where scripts/build_frontend places the built React bundle.
_STATIC_DIR = Path(__file__).resolve().parent / "static"

# Windows machines sometimes carry registry MIME mappings that mark .js as
# text/plain, which makes browsers refuse Vite's module scripts. Pin the
# types the bundle relies on so serving works identically everywhere.
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("application/javascript", ".mjs")
mimetypes.add_type("text/css", ".css")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup/shutdown hooks."""
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
    intake = PromptIntake(
        PolicyEngine(strict_mode=settings.governance_strict_mode),
        max_length=settings.governance_max_prompt_length,
    )
    app.state.prompt_intake = intake
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
    # The shared in-memory state store: live sessions/runs, served by the
    # status APIs and streamed over WebSockets from Step 13. Purely in-memory
    # — nothing to tear down on shutdown.
    state_store = StateStore(max_finished_runs=settings.state_max_finished_runs)
    app.state.state_store = state_store
    # Bridge store mutations to the /ws endpoint (docs/Architecture.md:
    # events.py is the only path between them; the store stays WS-ignorant).
    event_bus = EventBus()
    state_store.set_notify(event_bus.publish)
    app.state.event_bus = event_bus
    # Background agent execution (Step 14): spawned by the main graph's
    # agent_spawn node, sharing the single runtime/store/audit stack.
    agent_runner = AgentRunner(
        runtime=runtime,
        store=state_store,
        audit=audit_service,
        workers=settings.agent_workers,
    )
    agent_runner.start()
    app.state.agent_runner = agent_runner
    app.state.prompt_pipeline = PromptPipeline(
        intake=intake,
        runtime=runtime,
        audit=audit_service,
        store=state_store,
        timeout_seconds=settings.llm_timeout_seconds,
        runner=agent_runner,
    )
    try:
        yield
    finally:
        # Cancel running/pending agents first so their cancellation audit
        # events are still queued, then drain queued audit events before
        # tearing down the engine they write through.
        await agent_runner.close()
        await audit_service.close()
        runtime.close()
        await db.dispose_engine()
        logger.info("LunaBlue backend shutting down")


def _register_frontend(app: FastAPI, static_dir: Path) -> None:
    """Serve the built React bundle from ``static_dir`` at the root path.

    Registered after the ``/api`` router so API routing always wins: the
    catch-all only sees requests no earlier route matched, and it still
    answers unknown ``/api``/``/ws`` paths with a JSON 404 rather than the
    SPA fallback.
    """
    root = static_dir.resolve()
    index_file = root / "index.html"

    # All methods, so an unknown /api path keeps its JSON 404 on POST etc.
    # (a GET/HEAD-only route would turn those into bare 405s).
    @app.api_route(
        "/{path:path}",
        methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"],
        include_in_schema=False,
    )
    async def serve_frontend(request: Request, path: str) -> Response:
        if path in ("api", "ws") or path.startswith(("api/", "ws/")):
            raise HTTPException(status_code=404, detail="Not Found")
        if request.method not in ("GET", "HEAD"):
            raise HTTPException(
                status_code=405,
                detail="Method Not Allowed",
                headers={"Allow": "GET, HEAD"},
            )
        if not index_file.is_file():
            # Dev mode: no bundle has been built yet. Point at the workflow
            # instead of erroring.
            return JSONResponse(
                status_code=200 if path == "" else 404,
                content={
                    "detail": "Frontend bundle not built.",
                    "hint": (
                        "Run scripts/build_frontend to serve the UI from this "
                        "process, or use the Vite dev server: "
                        "cd frontend && npm run dev."
                    ),
                    "api": "/api/health",
                },
            )
        if path:
            candidate = (root / path).resolve()
            if candidate.is_relative_to(root) and candidate.is_file():
                # Vite content-hashes everything under assets/, so those are
                # immutable; index.html and other root files must revalidate.
                cache = (
                    "public, max-age=31536000, immutable"
                    if path.startswith("assets/")
                    else "no-cache"
                )
                return FileResponse(candidate, headers={"Cache-Control": cache})
        # Root, or an unknown path: SPA fallback for client-side routing.
        return FileResponse(index_file, headers={"Cache-Control": "no-cache"})


def create_app(static_dir: Path | None = None) -> FastAPI:
    """Build a fresh application instance (tests create isolated copies).

    ``static_dir`` overrides where the built frontend is served from
    (tests point it at fabricated bundles); production uses the packaged
    ``app/static/`` directory.
    """
    app = FastAPI(title="LunaBlue", version=__version__, lifespan=lifespan)
    app.include_router(api_router, prefix="/api")
    # Live-state streaming at /ws (no /api prefix; the dev proxy and the SPA
    # catch-all both reserve the bare path).
    app.include_router(websocket.router)
    # Must stay last: the SPA catch-all matches every path not claimed above.
    _register_frontend(app, static_dir or _STATIC_DIR)
    return app


app = create_app()
