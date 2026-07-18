"""Tests for the embeddings backfill job (``app.audit.embeddings_backfill``)."""

import pytest
from sqlalchemy import insert

from app.audit import db, models, vectors
from app.audit.embeddings_backfill import backfill, count_missing
from tests.backend.fakes import make_embedding_runtime

TEST_DIMS = 4


@pytest.fixture
async def vec_store(audit_db):
    ready = await vectors.ensure_schema(db.get_engine(), TEST_DIMS)
    if not ready:
        pytest.skip("sqlite-vec extension unavailable on this Python build")
    return audit_db


async def _seed_turns() -> None:
    """Three requests: r1 with a response, r2 without, r3 failed (NULL)."""
    async with db.session_scope() as session:
        for rid in ("r1", "r2", "r3"):
            await session.execute(
                insert(models.PromptRequest).values(
                    request_id=rid, raw_prompt=f"prompt {rid}"
                )
            )
        await session.execute(
            insert(models.PromptResponse).values(
                request_id="r1", final_output="response r1"
            )
        )
        await session.execute(
            insert(models.PromptResponse).values(
                request_id="r3", final_output=None
            )
        )


async def test_count_missing(vec_store):
    await _seed_turns()
    missing = await count_missing()
    # Failed runs (NULL final_output) are not embeddable.
    assert missing == {"prompt": 3, "response": 1}


async def test_backfill_embeds_all_and_is_idempotent(vec_store, tmp_path):
    await _seed_turns()
    runtime, fake = make_embedding_runtime(tmp_path, dimensions=TEST_DIMS)

    written = await backfill(runtime, batch_size=2)
    assert written == {"prompt": 3, "response": 1}
    assert await count_missing() == {"prompt": 0, "response": 0}
    async with db.session_scope() as session:
        assert await vectors.count_embeddings(session) == 4
    assert all(call.startswith("search_document: ") for call in fake.calls)

    # Second run: nothing left to do, nothing re-embedded.
    fake.calls.clear()
    assert await backfill(runtime) == {"prompt": 0, "response": 0}
    assert fake.calls == []


async def test_backfill_resumes_after_partial_run(vec_store, tmp_path):
    """Live-indexed rows are skipped: backfill only fills the gaps."""
    await _seed_turns()
    runtime, _ = make_embedding_runtime(tmp_path, dimensions=TEST_DIMS)
    async with db.session_scope() as session:
        await vectors.insert_embedding(
            session,
            request_id="r1",
            kind=vectors.KIND_PROMPT,
            model_id="fake",
            vector=[1.0, 0.0, 0.0, 0.0],
        )
    written = await backfill(runtime)
    assert written == {"prompt": 2, "response": 1}
    assert await count_missing() == {"prompt": 0, "response": 0}
