"""Typed application configuration.

All configuration flows through this module: the rest of the codebase gets
settings via :func:`get_settings` and never reads ``os.environ`` directly.
Field names match the variables documented in the repo-root ``.env.example``.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# The .env file lives at the repository root (next to .env.example), two
# levels above this file. A local backend/.env is also honored and wins,
# since uvicorn is normally launched from backend/.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_REPO_ROOT_ENV = _REPO_ROOT / ".env"


class Settings(BaseSettings):
    """Application settings loaded from the environment and ``.env``."""

    model_config = SettingsConfigDict(
        env_file=(str(_REPO_ROOT_ENV), ".env"),
        extra="ignore",
        protected_namespaces=(),
    )

    # SQLAlchemy URL for the audit database (Step 21: file-based SQLite).
    # Relative paths are anchored at the repository root — see
    # resolved_database_url.
    database_url: str = "sqlite+aiosqlite:///./data/lunablue.db"
    model_path: str = "./models/model.gguf"
    llm_context_size: int = 4096
    llm_gpu_layers: int = 0
    llm_max_tokens: int = 512
    llm_temperature: float = 0.7
    llm_timeout_seconds: float = 120.0
    # Per-call generation timeout (Step 17); 0 disables the guard.
    llm_generation_timeout_seconds: float = 120.0
    # Busy guard: reject new prompts with 503 when this many generations are
    # already queued/in flight on the runtime; 0 disables the guard.
    llm_max_queue_depth: int = 16
    # Closed-loop prompt processing: internal LLM prompt enhancement before
    # review, and the per-session rolling chat summary injected into it.
    # Both are internal-only — never exposed to the user.
    prompt_enhancement_enabled: bool = True
    prompt_enhancement_max_tokens: int = 512
    session_summary_enabled: bool = True
    session_summary_max_chars: int = 2000
    session_summary_max_tokens: int = 600
    # Identity fields pinned into every injected chat summary (Step 20):
    # stored outside the LLM-maintained rolling buffer, so they survive
    # resets and re-summarization. Runtime-editable via PUT /api/identity
    # (in-memory override). Only take effect while session_summary_enabled.
    identity_name: str = ""
    identity_age: str = ""
    identity_occupation: str = ""
    identity_personality: str = ""
    identity_interests: str = ""
    host: str = "127.0.0.1"
    port: int = 8000
    ws_enabled: bool = True
    # Server → client heartbeat interval on /ws; 0 disables heartbeats.
    ws_heartbeat_seconds: float = 30.0
    governance_strict_mode: bool = False
    governance_max_prompt_length: int = 32_000
    state_max_finished_runs: int = 256
    state_max_finished_agents: int = 256
    agent_workers: int = 1
    # Runaway-agent guards (Step 17); 0 disables each limit.
    agent_timeout_seconds: float = 600.0
    agent_max_steps: int = 16
    # Audit writer: bounded queue size and how often sustained overflow is
    # reported (one aggregate warning per interval instead of per-event spam).
    audit_max_queue_size: int = 1000
    audit_drop_log_interval_seconds: float = 30.0
    # Redaction of secrets/PII before audit rows are written (Step 17).
    audit_redaction_enabled: bool = False
    # Extra regex patterns (JSON array of strings) masked on top of the
    # built-in secret patterns when redaction is enabled.
    audit_redaction_patterns: list[str] = []
    # Retention window in days for audit rows; 0 keeps rows forever. Applied
    # by scripts/retention (see docs/DataRetention.md).
    audit_retention_days: int = 0
    # Per-table overrides (JSON object: table name -> days), e.g.
    # {"agent_events": 30}. Tables: sessions, prompt_requests,
    # prompt_responses, agent_events.
    audit_retention_overrides: dict[str, int] = {}
    # When true, startup validation also verifies the database answers a
    # trivial query (otherwise connectivity is only reported via readiness).
    startup_validate_db: bool = False
    log_level: str = "INFO"

    @property
    def resolved_database_path(self) -> Path | None:
        """The SQLite database file as an absolute path (None for non-SQLite
        URLs).

        Relative paths (the default ``./data/lunablue.db``) are anchored at
        the repository root, not the process CWD — uvicorn is normally
        launched from ``backend/``, which would otherwise silently create
        ``backend/data/``. Mirrors :attr:`resolved_model_path`.
        """
        from sqlalchemy.engine import make_url

        url = make_url(self.database_url)
        if url.get_backend_name() != "sqlite" or not url.database:
            return None
        path = Path(url.database)
        return path if path.is_absolute() else (_REPO_ROOT / path).resolve()

    @property
    def resolved_database_url(self) -> str:
        """``database_url`` with a relative SQLite path made absolute.

        Built with ``as_posix()`` so Windows drive-letter paths keep the
        ``sqlite+aiosqlite:///C:/...`` form. Non-SQLite and absolute-path
        URLs pass through unchanged.
        """
        path = self.resolved_database_path
        if path is None:
            return self.database_url
        from sqlalchemy.engine import make_url

        url = make_url(self.database_url).set(database=path.as_posix())
        return url.render_as_string(hide_password=False)

    @property
    def resolved_model_path(self) -> Path:
        """``model_path`` as an absolute path.

        Relative values (the ``.env.example`` default ``./models/model.gguf``)
        are anchored at the repository root, not the process CWD — uvicorn is
        normally launched from ``backend/``, which would otherwise silently
        look in ``backend/models/``.
        """
        path = Path(self.model_path)
        return path if path.is_absolute() else (_REPO_ROOT / path).resolve()


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide :class:`Settings`, loaded once and cached.

    Tests can call ``get_settings.cache_clear()`` or override the FastAPI
    dependency to inject their own instance.
    """
    return Settings()
