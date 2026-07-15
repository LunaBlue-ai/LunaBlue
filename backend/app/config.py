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

    database_url: str = (
        "postgresql+asyncpg://lunablue:lunablue@localhost:5432/lunablue"
    )
    model_path: str = "./models/model.gguf"
    llm_context_size: int = 4096
    llm_gpu_layers: int = 0
    llm_max_tokens: int = 512
    llm_temperature: float = 0.7
    llm_timeout_seconds: float = 120.0
    host: str = "127.0.0.1"
    port: int = 8000
    ws_enabled: bool = True
    governance_strict_mode: bool = False
    governance_max_prompt_length: int = 32_000
    state_max_finished_runs: int = 256
    agent_workers: int = 1
    log_level: str = "INFO"

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
