"""Application factory for the LunaBlue backend."""

import asyncio
import logging
import mimetypes
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response

from app import __version__
from app.api import websocket
from app.api.errors import install_error_handling
from app.api.routes import api_router
from app.audit import db
from app.audit.redaction import Redactor
from app.audit.service import AuditService
from app.config import get_settings
from app.governance.intake import PromptIntake
from app.governance.policy import PolicyEngine
from app.llm.runtime import (
    LlamaRuntime,
    LlamaRuntimeUnavailableError,
    ModelNotFoundError,
)
from app.orchestration.pipeline import PromptPipeline
from app.orchestration.runner import AgentRunner
from app.orchestration.summarizer import SessionSummarizer
from app.startup import (
    StartupValidationError,
    check_database_connects,
    validate_settings,
)
from app.state.events import EventBus
from app.state.identity import IdentityStore
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
    # Fail-fast startup validation (Step 17): every problem is collected and
    # reported in one actionable message before anything is constructed.
    problems, warnings = validate_settings(settings, static_dir=_STATIC_DIR)
    if settings.startup_validate_db and not problems:
        db_problem = await check_database_connects(settings.resolved_database_url)
        if db_problem is not None:
            problems.append(db_problem)
    if problems:
        error = StartupValidationError(problems)
        logger.error("%s", error)
        raise error
    for warning in warnings:
        logger.warning("%s", warning)
    # Step 21: the audit database is a local SQLite file created on demand —
    # apply the Alembic schema before anything connects. Runs in a worker
    # thread because env.py drives its own event loop (asyncio.run). A
    # failing migration aborts startup: an audit system must not boot
    # half-schema'd.
    await asyncio.to_thread(db.run_migrations, settings.resolved_database_url)
    db.init_engine(settings.resolved_database_url)
    redactor = (
        Redactor(extra_patterns=settings.audit_redaction_patterns)
        if settings.audit_redaction_enabled
        else None
    )
    audit_service = AuditService(
        settings.audit_max_queue_size,
        redactor=redactor,
        drop_log_interval=settings.audit_drop_log_interval_seconds,
    )
    audit_service.start()
    app.state.audit_service = audit_service
    intake = PromptIntake(
        PolicyEngine(strict_mode=settings.governance_strict_mode),
        max_length=settings.governance_max_prompt_length,
    )
    app.state.prompt_intake = intake
    # The single global LLM runtime (docs/Architecture.md). Loading is
    # deliberately fail-fast: a missing model file or an unloadable
    # llama-cpp-python build (e.g. a CUDA wheel mismatching the driver)
    # aborts startup with an actionable message rather than serving a
    # half-alive process.
    runtime = LlamaRuntime(
        model_path=str(settings.resolved_model_path),
        context_size=settings.llm_context_size,
        gpu_layers=settings.llm_gpu_layers,
        max_tokens=settings.llm_max_tokens,
        temperature=settings.llm_temperature,
        generation_timeout_seconds=settings.llm_generation_timeout_seconds,
    )
    try:
        runtime.load()
    except (ModelNotFoundError, LlamaRuntimeUnavailableError) as exc:
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
    state_store = StateStore(
        max_finished_runs=settings.state_max_finished_runs,
        max_finished_agents=settings.state_max_finished_agents,
    )
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
        timeout_seconds=settings.agent_timeout_seconds,
        max_steps=settings.agent_max_steps,
    )
    agent_runner.start()
    app.state.agent_runner = agent_runner
    # Closed-loop prompt processing: the rolling per-session chat summary,
    # maintained in the background after each completed turn.
    summarizer = None
    if settings.session_summary_enabled:
        summarizer = SessionSummarizer(
            runtime=runtime,
            store=state_store,
            max_chars=settings.session_summary_max_chars,
            max_tokens=settings.session_summary_max_tokens,
        )
    app.state.session_summarizer = summarizer
    # Identity fields (Step 20): env defaults, runtime-editable via
    # PUT /api/identity; pinned into every injected chat summary. In-memory
    # — nothing to tear down.
    identity = IdentityStore.from_settings(settings)
    app.state.identity = identity
    app.state.prompt_pipeline = PromptPipeline(
        intake=intake,
        runtime=runtime,
        audit=audit_service,
        store=state_store,
        timeout_seconds=settings.llm_timeout_seconds,
        runner=agent_runner,
        max_queue_depth=settings.llm_max_queue_depth,
        summarizer=summarizer,
        enhancement_enabled=settings.prompt_enhancement_enabled,
        enhancement_max_tokens=settings.prompt_enhancement_max_tokens,
        identity=identity,
        summary_max_chars=settings.session_summary_max_chars,
    )
    try:
        yield
    finally:
        # Pending summary updates are disposable in-memory state — cancel
        # them first so nothing new enters the generation queue, then cancel
        # running/pending agents so their cancellation audit events are still
        # queued, then drain queued audit events before tearing down the
        # engine they write through.
        if summarizer is not None:
            await summarizer.aclose()
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
    # Request-id middleware plus the consistent error envelope (Step 17,
    # api/errors.py): every non-2xx response carries code/message/request_id.
    install_error_handling(app)
    app.include_router(api_router, prefix="/api")
    # Live-state streaming at /ws (no /api prefix; the dev proxy and the SPA
    # catch-all both reserve the bare path).
    app.include_router(websocket.router)
    # Must stay last: the SPA catch-all matches every path not claimed above.
    _register_frontend(app, static_dir or _STATIC_DIR)
    return app


app = create_app()
