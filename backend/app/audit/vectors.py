"""sqlite-vec vector store for prompt/response embeddings.

The relational metadata lives in the Alembic-managed ``prompt_embeddings``
table (``app.audit.models.PromptEmbedding``); the vectors themselves live in
the ``vec_prompt_embeddings`` vec0 virtual table with ``rowid`` equal to the
metadata row's ``id``. The virtual table is created here at runtime —
deliberately outside Alembic, since vec0 tables (and the shadow tables vec0
creates alongside) cannot be expressed as SQLAlchemy metadata; autogenerate
excludes them via ``models.include_object_for_autogenerate``.

Search is brute-force KNN (sqlite-vec has no ANN index); at this
application's scale (thousands of turns) that is single-digit milliseconds.
"""

import logging
import struct
from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from sqlalchemy import text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.audit import db
from app.audit.models import PromptEmbedding

logger = logging.getLogger(__name__)

VEC_TABLE = "vec_prompt_embeddings"

KIND_PROMPT = "prompt"
KIND_RESPONSE = "response"


def serialize(vector: Sequence[float]) -> bytes:
    """Pack a vector as the little-endian float32 blob vec0 expects."""
    return struct.pack(f"{len(vector)}f", *vector)


async def ensure_schema(engine: AsyncEngine, dims: int) -> bool:
    """Create the vec0 virtual table if missing; True when usable.

    A dims mismatch with an existing table (EMBEDDING_DIMENSIONS changed
    after vectors were stored) disables the store with an actionable
    warning rather than silently mixing incompatible vectors.
    """
    async with engine.begin() as conn:
        # The extension loads lazily in the connect listener; only after a
        # connection exists does vec_available() reflect reality.
        if not db.vec_available():
            return False
        existing = (
            await conn.execute(
                text(
                    "SELECT sql FROM sqlite_master "
                    "WHERE type = 'table' AND name = :name"
                ),
                {"name": VEC_TABLE},
            )
        ).scalar()
        if existing is None:
            await conn.execute(
                text(
                    f"CREATE VIRTUAL TABLE {VEC_TABLE} "
                    f"USING vec0(embedding float[{dims}])"
                )
            )
            return True
        if f"float[{dims}]" not in existing:
            logger.warning(
                "%s exists with different dimensions than "
                "EMBEDDING_DIMENSIONS=%d - embedding storage disabled. To "
                "re-embed at the new size: stop the server, run "
                "\"DROP TABLE %s; DELETE FROM prompt_embeddings;\" against "
                "the database, then run the backfill script.",
                VEC_TABLE,
                dims,
                VEC_TABLE,
            )
            return False
        return True


async def insert_embedding(
    session: AsyncSession,
    *,
    request_id: str,
    kind: str,
    model_id: str | None,
    vector: Sequence[float],
) -> bool:
    """Store one embedding (metadata row + vector, one transaction).

    Idempotent per (request_id, kind): an existing embedding is kept and
    False is returned. The vec0 row shares the metadata row's id as rowid.
    """
    result = await session.execute(
        sqlite_insert(PromptEmbedding)
        .values(
            request_id=request_id,
            kind=kind,
            model_id=model_id,
            dims=len(vector),
        )
        .on_conflict_do_nothing(index_elements=["request_id", "kind"])
        .returning(PromptEmbedding.id)
    )
    row_id = result.scalar()
    if row_id is None:
        return False
    await session.execute(
        text(
            f"INSERT INTO {VEC_TABLE}(rowid, embedding) "
            "VALUES (:rowid, :embedding)"
        ),
        {"rowid": row_id, "embedding": serialize(vector)},
    )
    return True


@dataclass(frozen=True, slots=True)
class SearchHit:
    """One KNN result joined back to its source audit row."""

    request_id: str
    session_id: str | None
    kind: str
    distance: float
    text: str
    timestamp: datetime | None


async def knn_search(
    session: AsyncSession,
    *,
    vector: Sequence[float],
    k: int,
    kind: str | None = None,
) -> list[SearchHit]:
    """Nearest stored embeddings for ``vector``, closest first.

    ``kind`` filters to prompt or response embeddings. The kind filter is
    applied after the vec0 KNN (metadata lives in the relational table),
    so the KNN over-fetches to keep filtered result counts near ``k``.
    """
    fetch_k = k if kind is None else k * 4
    rows = (
        await session.execute(
            text(
                f"""
                SELECT
                    pe.request_id,
                    pr.session_id,
                    pe.kind,
                    v.distance,
                    CASE pe.kind
                        WHEN :kind_prompt THEN pr.raw_prompt
                        ELSE (
                            SELECT resp.final_output
                            FROM prompt_responses AS resp
                            WHERE resp.request_id = pe.request_id
                                AND resp.final_output IS NOT NULL
                            ORDER BY resp.id DESC
                            LIMIT 1
                        )
                    END AS content,
                    pr.timestamp
                FROM (
                    SELECT rowid, distance
                    FROM {VEC_TABLE}
                    WHERE embedding MATCH :query AND k = :fetch_k
                    ORDER BY distance
                ) AS v
                JOIN prompt_embeddings AS pe ON pe.id = v.rowid
                JOIN prompt_requests AS pr ON pr.request_id = pe.request_id
                WHERE (:kind IS NULL OR pe.kind = :kind)
                ORDER BY v.distance
                LIMIT :k
                """
            ),
            {
                "query": serialize(vector),
                "fetch_k": fetch_k,
                "k": k,
                "kind": kind,
                "kind_prompt": KIND_PROMPT,
            },
        )
    ).all()
    return [
        SearchHit(
            request_id=row.request_id,
            session_id=row.session_id,
            kind=row.kind,
            distance=float(row.distance),
            text=row.content or "",
            timestamp=row.timestamp,
        )
        for row in rows
    ]


async def count_embeddings(session: AsyncSession) -> int:
    result = await session.execute(
        text("SELECT count(*) FROM prompt_embeddings")
    )
    return int(result.scalar() or 0)


async def delete_orphan_vectors(session: AsyncSession) -> int:
    """Remove vec0 rows whose metadata row is gone.

    FK cascades cover ``prompt_embeddings`` but never the virtual table;
    retention calls this after its deletes.
    """
    if not db.vec_available():
        return 0
    exists = (
        await session.execute(
            text(
                "SELECT 1 FROM sqlite_master "
                "WHERE type = 'table' AND name = :name"
            ),
            {"name": VEC_TABLE},
        )
    ).scalar()
    if not exists:
        return 0
    result = await session.execute(
        text(
            f"DELETE FROM {VEC_TABLE} "
            "WHERE rowid NOT IN (SELECT id FROM prompt_embeddings)"
        )
    )
    return result.rowcount or 0
