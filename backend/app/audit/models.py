"""SQLAlchemy models for the audit schema.

Four tables per docs/Components/AUDIT.md: ``sessions``, ``prompt_requests``,
``prompt_responses``, and ``agent_events``. The schema is owned by this
service and changed only through Alembic migrations; Alembic autogenerate
compares against ``Base.metadata``.

Identifiers (session/request/user/agent ids) are strings so the in-memory
runtime stays free to choose its own id format.

Step 21 (SQLite migration): column types are dialect-portable — plain
``JSON`` instead of JSONB, integer primary keys that map to SQLite's rowid
autoincrement, and :class:`TZDateTime` to round-trip timezone-aware UTC
through SQLite's naive datetime storage.
"""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def include_object_for_autogenerate(
    obj: Any, name: str | None, type_: str, reflected: bool, compare_to: Any
) -> bool:
    """Alembic autogenerate filter shared by migrations/env.py and the
    model/migration parity test.

    The sqlite-vec virtual table (``vec_prompt_embeddings``) and its shadow
    tables (``vec_prompt_embeddings_chunks`` etc.) live outside Alembic —
    they are created at runtime by ``app.audit.vectors.ensure_schema`` —
    so autogenerate must never see them as tables to drop.
    """
    return not (type_ == "table" and (name or "").startswith("vec_"))


class TZDateTime(TypeDecorator):
    """Timezone-aware UTC datetimes over SQLite's naive storage.

    SQLite stores datetimes as naive text; the audit writer always passes
    timezone-aware UTC values and retention compares against timezone-aware
    cutoffs. Normalizing on both the bind side (store naive UTC) and the
    result side (return aware UTC) keeps those comparisons — and the
    timestamps surfaced through ``fetch_agent_events`` — correct without
    scattering conversions through the callers.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any):
        if value is None:
            return None
        if value.tzinfo is None:
            # Naive input is assumed UTC (the writer never produces it).
            return value
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Any):
        if value is None:
            return None
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc)
        return value.replace(tzinfo=timezone.utc)


# SQLite autoincrement only works on INTEGER PRIMARY KEY (not BIGINT);
# SQLite INTEGER is 64-bit anyway, so nothing is lost.
BigIntPK = BigInteger().with_variant(Integer, "sqlite")

# Deterministic constraint/index names so autogenerate diffs stay stable.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Session(Base):
    """A conversation/session under which prompt requests are grouped."""

    __tablename__ = "sessions"

    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        TZDateTime(), server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime(), server_default=func.now(), onupdate=func.now()
    )
    meta: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSON)


class PromptRequest(Base):
    """An inbound prompt: raw text plus the governance-reviewed form."""

    __tablename__ = "prompt_requests"

    request_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str | None] = mapped_column(
        ForeignKey("sessions.session_id", ondelete="SET NULL")
    )
    timestamp: Mapped[datetime] = mapped_column(
        TZDateTime(), server_default=func.now(), index=True
    )
    user_id: Mapped[str | None] = mapped_column(String(64))
    raw_prompt: Mapped[str] = mapped_column(Text)
    reviewed_prompt: Mapped[str | None] = mapped_column(Text)
    prompt_version: Mapped[str | None] = mapped_column(String(64))
    governance: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class PromptResponse(Base):
    """The LLM output and the final assistant output for a request."""

    __tablename__ = "prompt_responses"

    id: Mapped[int] = mapped_column(
        BigIntPK, primary_key=True, autoincrement=True
    )
    request_id: Mapped[str] = mapped_column(
        ForeignKey("prompt_requests.request_id", ondelete="CASCADE")
    )
    timestamp: Mapped[datetime] = mapped_column(
        TZDateTime(), server_default=func.now(), index=True
    )
    llm_output: Mapped[str | None] = mapped_column(Text)
    final_output: Mapped[str | None] = mapped_column(Text)
    model_id: Mapped[str | None] = mapped_column(String(128))
    usage: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class PromptEmbedding(Base):
    """Metadata for one stored embedding vector (prompt or response text).

    The vector itself lives in the ``vec_prompt_embeddings`` sqlite-vec
    virtual table with ``rowid == id`` (see ``app.audit.vectors``); this
    table carries the relational metadata Alembic can manage. One embedding
    per (request, kind): re-runs of the indexer/backfill are no-ops.
    """

    __tablename__ = "prompt_embeddings"
    __table_args__ = (UniqueConstraint("request_id", "kind"),)

    id: Mapped[int] = mapped_column(
        BigIntPK, primary_key=True, autoincrement=True
    )
    request_id: Mapped[str] = mapped_column(
        ForeignKey("prompt_requests.request_id", ondelete="CASCADE"),
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(16))  # "prompt" | "response"
    model_id: Mapped[str | None] = mapped_column(String(128))
    dims: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        TZDateTime(), server_default=func.now()
    )


class AgentEvent(Base):
    """Agent lifecycle events and state transitions."""

    __tablename__ = "agent_events"

    id: Mapped[int] = mapped_column(
        BigIntPK, primary_key=True, autoincrement=True
    )
    agent_id: Mapped[str] = mapped_column(String(64), index=True)
    request_id: Mapped[str | None] = mapped_column(
        ForeignKey("prompt_requests.request_id", ondelete="SET NULL")
    )
    timestamp: Mapped[datetime] = mapped_column(
        TZDateTime(), server_default=func.now(), index=True
    )
    event_type: Mapped[str] = mapped_column(String(64))
    state: Mapped[str | None] = mapped_column(String(64))
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
