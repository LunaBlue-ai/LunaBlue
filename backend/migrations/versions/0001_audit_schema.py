"""audit schema

Revision ID: 0001
Revises:
Create Date: 2026-07-12
Rewritten for SQLite (Step 21): dialect-portable DDL — plain JSON instead of
JSONB, CURRENT_TIMESTAMP defaults instead of now(), and integer primary keys
that map to SQLite's rowid autoincrement. Safe to rewrite in place: this is
the only revision and all Postgres databases are being abandoned.

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# SQLite autoincrement requires INTEGER PRIMARY KEY (64-bit anyway); other
# dialects keep BIGINT. Mirrors models.BigIntPK.
_BIG_INT_PK = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "sessions",
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("session_id", name=op.f("pk_sessions")),
    )
    op.create_index(
        op.f("ix_sessions_created_at"), "sessions", ["created_at"], unique=False
    )

    op.create_table(
        "prompt_requests",
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=True),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(length=64), nullable=True),
        sa.Column("raw_prompt", sa.Text(), nullable=False),
        sa.Column("reviewed_prompt", sa.Text(), nullable=True),
        sa.Column("prompt_version", sa.String(length=64), nullable=True),
        sa.Column("governance", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.session_id"],
            name=op.f("fk_prompt_requests_session_id_sessions"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("request_id", name=op.f("pk_prompt_requests")),
    )
    op.create_index(
        op.f("ix_prompt_requests_timestamp"),
        "prompt_requests",
        ["timestamp"],
        unique=False,
    )

    op.create_table(
        "prompt_responses",
        sa.Column("id", _BIG_INT_PK, autoincrement=True, nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("llm_output", sa.Text(), nullable=True),
        sa.Column("final_output", sa.Text(), nullable=True),
        sa.Column("model_id", sa.String(length=128), nullable=True),
        sa.Column("usage", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["prompt_requests.request_id"],
            name=op.f("fk_prompt_responses_request_id_prompt_requests"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_prompt_responses")),
    )
    op.create_index(
        op.f("ix_prompt_responses_timestamp"),
        "prompt_responses",
        ["timestamp"],
        unique=False,
    )

    op.create_table(
        "agent_events",
        sa.Column("id", _BIG_INT_PK, autoincrement=True, nullable=False),
        sa.Column("agent_id", sa.String(length=64), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=64), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["prompt_requests.request_id"],
            name=op.f("fk_agent_events_request_id_prompt_requests"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_events")),
    )
    op.create_index(
        op.f("ix_agent_events_agent_id"), "agent_events", ["agent_id"], unique=False
    )
    op.create_index(
        op.f("ix_agent_events_timestamp"), "agent_events", ["timestamp"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_agent_events_timestamp"), table_name="agent_events")
    op.drop_index(op.f("ix_agent_events_agent_id"), table_name="agent_events")
    op.drop_table("agent_events")
    op.drop_index(op.f("ix_prompt_responses_timestamp"), table_name="prompt_responses")
    op.drop_table("prompt_responses")
    op.drop_index(op.f("ix_prompt_requests_timestamp"), table_name="prompt_requests")
    op.drop_table("prompt_requests")
    op.drop_index(op.f("ix_sessions_created_at"), table_name="sessions")
    op.drop_table("sessions")
