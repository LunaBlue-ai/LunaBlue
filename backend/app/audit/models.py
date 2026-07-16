"""SQLAlchemy models for the audit schema.

Four tables per docs/Components/AUDIT.md: ``sessions``, ``prompt_requests``,
``prompt_responses``, and ``agent_events``. The schema is owned by this
service and changed only through Alembic migrations; Alembic autogenerate
compares against ``Base.metadata``.

Identifiers (session/request/user/agent ids) are strings so the in-memory
runtime stays free to choose its own id format.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, MetaData, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

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
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    meta: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB)


class PromptRequest(Base):
    """An inbound prompt: raw text plus the governance-reviewed form."""

    __tablename__ = "prompt_requests"

    request_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str | None] = mapped_column(
        ForeignKey("sessions.session_id", ondelete="SET NULL")
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    user_id: Mapped[str | None] = mapped_column(String(64))
    raw_prompt: Mapped[str] = mapped_column(Text)
    reviewed_prompt: Mapped[str | None] = mapped_column(Text)
    prompt_version: Mapped[str | None] = mapped_column(String(64))
    governance: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class PromptResponse(Base):
    """The LLM output and the final assistant output for a request."""

    __tablename__ = "prompt_responses"

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    request_id: Mapped[str] = mapped_column(
        ForeignKey("prompt_requests.request_id", ondelete="CASCADE")
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    llm_output: Mapped[str | None] = mapped_column(Text)
    final_output: Mapped[str | None] = mapped_column(Text)
    model_id: Mapped[str | None] = mapped_column(String(128))
    usage: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class AgentEvent(Base):
    """Agent lifecycle events and state transitions."""

    __tablename__ = "agent_events"

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    agent_id: Mapped[str] = mapped_column(String(64), index=True)
    request_id: Mapped[str | None] = mapped_column(
        ForeignKey("prompt_requests.request_id", ondelete="SET NULL")
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    event_type: Mapped[str] = mapped_column(String(64))
    state: Mapped[str | None] = mapped_column(String(64))
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
