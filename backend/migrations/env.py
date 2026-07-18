"""Alembic environment for the audit schema.

The database URL comes from the application settings (which read
DATABASE_URL / .env) rather than alembic.ini, and autogenerate compares
against the models' metadata.
"""

import asyncio
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.audit.models import Base, include_object_for_autogenerate
from app.config import get_settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    # Precedence: -x db_url=... (CLI one-offs, tests) > config.attributes
    # (the app lifespan's programmatic upgrade, Step 21) > settings.
    x_url = context.get_x_argument(as_dictionary=True).get("db_url")
    if x_url:
        return x_url
    attr_url = config.attributes.get("db_url")
    if attr_url:
        return attr_url
    return get_settings().resolved_database_url


def _ensure_sqlite_parent_dir(url: str) -> None:
    """Create the database file's parent directory for SQLite URLs.

    Migrations may be the first thing that ever touches the database (fresh
    checkout, standalone retention run), so the data directory cannot be
    assumed to exist.
    """
    parsed = make_url(url)
    if parsed.get_backend_name() == "sqlite" and parsed.database:
        Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a live database (--sql mode)."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_object=include_object_for_autogenerate,
    )

    with context.begin_transaction():
        context.run_migrations()


def _run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        include_object=include_object_for_autogenerate,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations over the async engine."""
    configuration = config.get_section(config.config_ini_section, {})
    url = _database_url()
    _ensure_sqlite_parent_dir(url)
    configuration["sqlalchemy.url"] = url
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
