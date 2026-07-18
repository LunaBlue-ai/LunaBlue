"""prompt embeddings metadata

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-18

Metadata table for stored embedding vectors (one row per request per kind:
"prompt" or "response"). The vectors themselves live in the sqlite-vec
virtual table ``vec_prompt_embeddings`` (rowid == prompt_embeddings.id),
which is created at runtime by ``app.audit.vectors.ensure_schema`` — never
by Alembic — and excluded from autogenerate via
``models.include_object_for_autogenerate``.

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# SQLite autoincrement requires INTEGER PRIMARY KEY (64-bit anyway); other
# dialects keep BIGINT. Mirrors models.BigIntPK.
_BIG_INT_PK = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "prompt_embeddings",
        sa.Column("id", _BIG_INT_PK, autoincrement=True, nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("model_id", sa.String(length=128), nullable=True),
        sa.Column("dims", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["prompt_requests.request_id"],
            name=op.f("fk_prompt_embeddings_request_id_prompt_requests"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_prompt_embeddings")),
        sa.UniqueConstraint(
            "request_id", "kind", name=op.f("uq_prompt_embeddings_request_id")
        ),
    )
    op.create_index(
        op.f("ix_prompt_embeddings_request_id"),
        "prompt_embeddings",
        ["request_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_prompt_embeddings_request_id"), table_name="prompt_embeddings"
    )
    op.drop_table("prompt_embeddings")
