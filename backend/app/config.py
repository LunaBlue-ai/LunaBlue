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
_REPO_ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    """Application settings loaded from the environment and ``.env``."""

    model_config = SettingsConfigDict(
        env_file=(str(_REPO_ROOT_ENV), ".env"),
        extra="ignore",
        protected_namespaces=(),
    )

    database_url: str = (
        "postgresql+psycopg://lunablue:lunablue@localhost:5432/lunablue"
    )
    model_path: str = "./models/model.gguf"
    llm_context_size: int = 4096
    llm_gpu_layers: int = 0
    host: str = "127.0.0.1"
    port: int = 8000
    ws_enabled: bool = True
    governance_strict_mode: bool = False
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide :class:`Settings`, loaded once and cached.

    Tests can call ``get_settings.cache_clear()`` or override the FastAPI
    dependency to inject their own instance.
    """
    return Settings()
