"""Backfill embeddings for audit rows stored before embeddings existed.

Invoked by ``scripts/backfill_embeddings`` (``python -m
app.audit.embeddings_backfill``). Loads the embedding model directly (no
server needed), finds ``prompt_requests`` / ``prompt_responses`` rows with
no stored embedding of the matching kind, embeds them in batches, and
writes vectors + metadata — one transaction per batch, so an interrupted
run leaves a consistent database and the next run picks up where it
stopped. Idempotent: rows that already have an embedding are skipped (the
same code path the live indexer writes through).

``--dry-run`` reports how many rows are missing embeddings without loading
the model or writing anything.
"""

import argparse
import asyncio
import logging
import sys

from sqlalchemy import func, select
from sqlalchemy.orm import aliased

from app.audit import db, models, vectors
from app.audit.vectors import KIND_PROMPT, KIND_RESPONSE
from app.config import get_settings
from app.llm.embedding import EmbeddingRuntime

logger = logging.getLogger(__name__)


def _missing_query(kind: str):
    """Rows of ``kind`` with no stored embedding: (request_id, text)."""
    embedded = (
        select(models.PromptEmbedding.request_id)
        .where(models.PromptEmbedding.kind == kind)
        .scalar_subquery()
    )
    if kind == KIND_PROMPT:
        return (
            select(
                models.PromptRequest.request_id,
                models.PromptRequest.raw_prompt,
            )
            .where(models.PromptRequest.request_id.not_in(embedded))
            .order_by(models.PromptRequest.request_id)
        )
    # Latest non-null final_output per request (failed runs store NULL).
    # The alias makes the subquery correlate against the outer
    # prompt_responses row instead of pulling it into its own FROM.
    inner = aliased(models.PromptResponse)
    latest = (
        select(func.max(inner.id))
        .where(
            inner.request_id == models.PromptResponse.request_id,
            inner.final_output.is_not(None),
        )
        .scalar_subquery()
    )
    return (
        select(
            models.PromptResponse.request_id,
            models.PromptResponse.final_output,
        )
        .where(
            models.PromptResponse.id == latest,
            models.PromptResponse.request_id.not_in(embedded),
        )
        .order_by(models.PromptResponse.request_id)
    )


async def count_missing() -> dict[str, int]:
    counts: dict[str, int] = {}
    async with db.session_scope() as session:
        for kind in (KIND_PROMPT, KIND_RESPONSE):
            counts[kind] = (
                await session.execute(
                    select(func.count()).select_from(
                        _missing_query(kind).subquery()
                    )
                )
            ).scalar_one()
    return counts


async def backfill(
    runtime: EmbeddingRuntime, *, batch_size: int = 128
) -> dict[str, int]:
    """Embed and store every missing row; returns rows written per kind."""
    written = {KIND_PROMPT: 0, KIND_RESPONSE: 0}
    for kind in (KIND_PROMPT, KIND_RESPONSE):
        while True:
            async with db.session_scope() as session:
                rows = (
                    await session.execute(
                        _missing_query(kind).limit(batch_size)
                    )
                ).all()
                if not rows:
                    break
                texts = [text or "" for _, text in rows]
                vecs = await runtime.embed(texts, prefix="search_document")
                for (request_id, _), vector in zip(rows, vecs):
                    if await vectors.insert_embedding(
                        session,
                        request_id=request_id,
                        kind=kind,
                        model_id=runtime.model_info["model_id"],
                        vector=vector,
                    ):
                        written[kind] += 1
            logger.info(
                "backfill: %d %s embedding(s) written so far",
                written[kind],
                kind,
            )
            if len(rows) < batch_size:
                break
    return written


async def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.audit.embeddings_backfill",
        description=(
            "Embed stored prompt/response rows that have no embedding yet "
            "(idempotent; safe to re-run and to interrupt)."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report missing-embedding counts without writing anything",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=128,
        help="rows embedded per transaction (default 128)",
    )
    args = parser.parse_args(argv)
    if args.batch_size < 1:
        parser.error("--batch-size must be >= 1")

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = get_settings()
    db_path = settings.resolved_database_path
    if db_path is not None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
    db.init_engine(settings.resolved_database_url)
    try:
        missing = await count_missing()
        print(
            f"missing embeddings: {missing[KIND_PROMPT]} prompt(s), "
            f"{missing[KIND_RESPONSE]} response(s)"
        )
        if args.dry_run or not any(missing.values()):
            return 0

        ready = await vectors.ensure_schema(
            db.get_engine(), settings.embedding_dimensions
        )
        if not ready:
            print(
                "error: the sqlite-vec store is unavailable (see the "
                "warning above).",
                file=sys.stderr,
            )
            return 1
        runtime = EmbeddingRuntime(
            model_path=str(settings.resolved_embedding_model_path),
            context_size=settings.embedding_context_size,
            gpu_layers=settings.embedding_gpu_layers,
            dimensions=settings.embedding_dimensions,
        )
        runtime.load()
        if not runtime.available:
            print(
                "error: embedding model unavailable "
                f"({runtime.last_error}). Fetch it with "
                "scripts/download_embedding_model.ps1 (or .sh).",
                file=sys.stderr,
            )
            return 1
        try:
            written = await backfill(runtime, batch_size=args.batch_size)
        finally:
            runtime.close()
        print(
            f"wrote {written[KIND_PROMPT]} prompt and "
            f"{written[KIND_RESPONSE]} response embedding(s)"
        )
        return 0
    finally:
        await db.dispose_engine()


if __name__ == "__main__":  # pragma: no cover - via scripts/backfill_embeddings
    raise SystemExit(asyncio.run(_main()))
