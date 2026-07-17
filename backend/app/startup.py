"""Fail-fast startup validation (Step 17).

Run by the ``main.py`` lifespan before anything is constructed: every
configured setting is checked coherently — model file present and readable,
database URL well-formed (optionally that it answers, flag-controlled),
numeric bounds, redaction patterns compile — and *all* problems are collected
into one :class:`StartupValidationError` with a single actionable message,
instead of the process dying on the first of several misconfigurations.

Non-fatal findings (e.g. a missing frontend bundle, which is normal in dev)
come back as warnings for the lifespan to log.
"""

import asyncio
import os
import re
from pathlib import Path

from sqlalchemy.engine import make_url

from app.config import Settings

# Retention windows may only target these audit tables (models.py).
RETENTION_TABLES = frozenset(
    {"sessions", "prompt_requests", "prompt_responses", "agent_events"}
)

_DB_PROBE_TIMEOUT_SECONDS = 5.0


class StartupValidationError(RuntimeError):
    """Configuration is invalid; the message lists every problem found."""

    def __init__(self, problems: list[str]) -> None:
        details = "\n".join(f"  - {problem}" for problem in problems)
        super().__init__(
            f"Startup validation failed ({len(problems)} problem(s)); "
            f"fix .env / environment and restart:\n{details}"
        )
        self.problems = problems


def _check_model_file(settings: Settings, problems: list[str]) -> None:
    path = settings.resolved_model_path
    if not path.is_file():
        problems.append(
            f"MODEL_PATH: model file not found: {str(path)!r}. Fetch the "
            "default model with scripts/download_model.ps1 (or .sh), or "
            "point MODEL_PATH at an existing GGUF file."
        )
        return
    try:
        with path.open("rb") as handle:
            handle.read(4)
    except OSError as exc:
        problems.append(
            f"MODEL_PATH: model file exists but is not readable: "
            f"{str(path)!r} ({type(exc).__name__})."
        )


def _check_database_url(settings: Settings, problems: list[str]) -> None:
    try:
        url = make_url(settings.database_url)
    except Exception as exc:
        problems.append(
            f"DATABASE_URL: not a valid SQLAlchemy URL ({type(exc).__name__}: "
            f"{exc})."
        )
        return
    if url.drivername != "sqlite+aiosqlite":
        problems.append(
            "DATABASE_URL: expected a sqlite+aiosqlite URL (Step 21 — the "
            f"audit store is a local SQLite file), got driver "
            f"{url.drivername!r}."
        )
        return
    # The database is a local file created on demand; what can actually be
    # misconfigured is the location. Verify the parent directory can exist
    # and is writable.
    path = settings.resolved_database_path
    if path is None:
        problems.append("DATABASE_URL: sqlite URL has no database path.")
        return
    parent = path.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
        probe = parent / f".write-probe-{os.getpid()}"
        probe.touch()
        probe.unlink()
    except OSError as exc:
        problems.append(
            f"DATABASE_URL: database directory {str(parent)!r} is not "
            f"writable ({type(exc).__name__}: {exc})."
        )


def _check_bounds(settings: Settings, problems: list[str]) -> None:
    def require(condition: bool, message: str) -> None:
        if not condition:
            problems.append(message)

    require(settings.llm_context_size >= 1, "LLM_CONTEXT_SIZE must be >= 1.")
    require(
        settings.llm_gpu_layers >= -1,
        "LLM_GPU_LAYERS must be >= -1 (-1 offloads all layers, 0 is CPU-only).",
    )
    require(settings.llm_max_tokens >= 1, "LLM_MAX_TOKENS must be >= 1.")
    require(
        0.0 <= settings.llm_temperature <= 2.0,
        "LLM_TEMPERATURE must be between 0 and 2.",
    )
    require(settings.llm_timeout_seconds > 0, "LLM_TIMEOUT_SECONDS must be > 0.")
    require(
        settings.llm_generation_timeout_seconds >= 0,
        "LLM_GENERATION_TIMEOUT_SECONDS must be >= 0 (0 disables the guard).",
    )
    require(
        settings.llm_max_queue_depth >= 0,
        "LLM_MAX_QUEUE_DEPTH must be >= 0 (0 disables the busy guard).",
    )
    require(
        settings.prompt_enhancement_max_tokens >= 1,
        "PROMPT_ENHANCEMENT_MAX_TOKENS must be >= 1.",
    )
    require(
        settings.session_summary_max_chars >= 1,
        "SESSION_SUMMARY_MAX_CHARS must be >= 1.",
    )
    require(
        settings.session_summary_max_tokens >= 1,
        "SESSION_SUMMARY_MAX_TOKENS must be >= 1.",
    )
    for env_name, value in (
        ("IDENTITY_NAME", settings.identity_name),
        ("IDENTITY_AGE", settings.identity_age),
        ("IDENTITY_OCCUPATION", settings.identity_occupation),
        ("IDENTITY_PERSONALITY", settings.identity_personality),
        ("IDENTITY_INTERESTS", settings.identity_interests),
    ):
        require(
            len(value) <= 200,
            f"{env_name} must be at most 200 characters.",
        )
    require(1 <= settings.port <= 65535, "PORT must be between 1 and 65535.")
    require(
        settings.ws_heartbeat_seconds >= 0,
        "WS_HEARTBEAT_SECONDS must be >= 0 (0 disables heartbeats).",
    )
    require(
        settings.governance_max_prompt_length >= 1,
        "GOVERNANCE_MAX_PROMPT_LENGTH must be >= 1.",
    )
    require(
        settings.state_max_finished_runs >= 1,
        "STATE_MAX_FINISHED_RUNS must be >= 1.",
    )
    require(
        settings.state_max_finished_agents >= 1,
        "STATE_MAX_FINISHED_AGENTS must be >= 1.",
    )
    require(settings.agent_workers >= 1, "AGENT_WORKERS must be >= 1.")
    require(
        settings.agent_timeout_seconds >= 0,
        "AGENT_TIMEOUT_SECONDS must be >= 0 (0 disables the guard).",
    )
    require(
        settings.agent_max_steps >= 0,
        "AGENT_MAX_STEPS must be >= 0 (0 disables the guard).",
    )
    require(
        settings.audit_max_queue_size >= 1, "AUDIT_MAX_QUEUE_SIZE must be >= 1."
    )
    require(
        settings.audit_drop_log_interval_seconds > 0,
        "AUDIT_DROP_LOG_INTERVAL_SECONDS must be > 0.",
    )
    require(
        settings.audit_retention_days >= 0,
        "AUDIT_RETENTION_DAYS must be >= 0 (0 disables retention).",
    )
    for table, days in settings.audit_retention_overrides.items():
        if table not in RETENTION_TABLES:
            problems.append(
                f"AUDIT_RETENTION_OVERRIDES: unknown table {table!r} "
                f"(expected one of {sorted(RETENTION_TABLES)})."
            )
        if days < 0:
            problems.append(
                f"AUDIT_RETENTION_OVERRIDES: window for {table!r} must be >= 0."
            )


def _check_redaction_patterns(settings: Settings, problems: list[str]) -> None:
    for pattern in settings.audit_redaction_patterns:
        try:
            re.compile(pattern)
        except re.error as exc:
            problems.append(
                f"AUDIT_REDACTION_PATTERNS: invalid regex {pattern!r} ({exc})."
            )


def validate_settings(
    settings: Settings, *, static_dir: Path | None = None
) -> tuple[list[str], list[str]]:
    """Validate every setting; returns ``(problems, warnings)``.

    Problems abort startup (via :class:`StartupValidationError` in the
    lifespan); warnings are logged and boot continues.
    """
    problems: list[str] = []
    warnings: list[str] = []

    _check_model_file(settings, problems)
    _check_database_url(settings, problems)
    _check_bounds(settings, problems)
    _check_redaction_patterns(settings, problems)

    # Static directory state is informational: serving the SPA from FastAPI is
    # optional (dev uses the Vite server), but a half-built bundle is worth
    # flagging loudly.
    if static_dir is not None:
        if not static_dir.is_dir():
            warnings.append(
                f"Frontend bundle not built ({static_dir}); the UI will not "
                "be served from this process. Run scripts/build_frontend, or "
                "use the Vite dev server."
            )
        elif not (static_dir / "index.html").is_file():
            warnings.append(
                f"Static directory {static_dir} exists but has no index.html; "
                "the bundle looks incomplete. Re-run scripts/build_frontend."
            )
    return problems, warnings


async def check_database_connects(database_url: str) -> str | None:
    """Optional boot-time connectivity probe (STARTUP_VALIDATE_DB=true).

    Returns None when the database answers a trivial query, else the problem
    description. Uses its own short-lived engine so a failure leaves nothing
    behind.
    """
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(database_url)
    try:
        async with asyncio.timeout(_DB_PROBE_TIMEOUT_SECONDS):
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        return None
    except Exception as exc:
        return (
            "DATABASE_URL: connectivity check failed (STARTUP_VALIDATE_DB is "
            f"enabled): {type(exc).__name__}: {exc}"
        )
    finally:
        await engine.dispose()
