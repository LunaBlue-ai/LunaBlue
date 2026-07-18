"""Tests for the background embedding indexer and its audit-service hook."""

from sqlalchemy import insert

import pytest

from app.audit import db, models, vectors
from app.audit.service import AuditService
from app.orchestration.indexer import EmbeddingIndexer
from tests.backend.fakes import make_embedding_runtime

TEST_DIMS = 4


@pytest.fixture
async def vec_store(audit_db):
    ready = await vectors.ensure_schema(db.get_engine(), TEST_DIMS)
    if not ready:
        pytest.skip("sqlite-vec extension unavailable on this Python build")
    return audit_db


async def _seed_request(request_id: str) -> None:
    async with db.session_scope() as session:
        await session.execute(
            insert(models.PromptRequest).values(
                request_id=request_id, raw_prompt="seed"
            )
        )


async def test_schedule_embeds_and_stores(vec_store, tmp_path):
    runtime, fake = make_embedding_runtime(tmp_path, dimensions=TEST_DIMS)
    indexer = EmbeddingIndexer(runtime)
    await _seed_request("r1")

    indexer.schedule("prompt", "r1", "what is the weather")
    await indexer.wait_idle()

    assert fake.calls == ["search_document: what is the weather"]
    async with db.session_scope() as session:
        assert await vectors.count_embeddings(session) == 1
        hits = await vectors.knn_search(
            session,
            vector=(await runtime.embed(
                ["what is the weather"], prefix="search_document"
            ))[0],
            k=1,
        )
    assert hits[0].request_id == "r1"
    assert hits[0].distance == pytest.approx(0.0, abs=1e-5)


async def test_schedule_skips_empty_text_and_unavailable_runtime(
    vec_store, tmp_path
):
    runtime, fake = make_embedding_runtime(tmp_path, dimensions=TEST_DIMS)
    indexer = EmbeddingIndexer(runtime)
    indexer.schedule("response", "r1", None)  # failed run: NULL output
    indexer.schedule("response", "r1", "")
    await indexer.wait_idle()
    assert fake.calls == []
    assert indexer.pending == 0

    runtime.close()  # unavailable now
    indexer.schedule("prompt", "r1", "text")
    await indexer.wait_idle()
    assert fake.calls == []


async def test_backlog_overflow_drops_with_warning(vec_store, tmp_path, caplog):
    runtime, _ = make_embedding_runtime(tmp_path, dimensions=TEST_DIMS)
    indexer = EmbeddingIndexer(runtime, max_pending=1)
    await _seed_request("r1")
    await _seed_request("r2")
    with caplog.at_level("WARNING", logger="app.orchestration.indexer"):
        indexer.schedule("prompt", "r1", "one")
        indexer.schedule("prompt", "r2", "two")  # over the cap: dropped
    await indexer.wait_idle()
    assert indexer.dropped_total == 1
    assert any("backlog full" in r.message for r in caplog.records)


async def test_failed_embed_is_contained(vec_store, tmp_path, caplog):
    runtime, fake = make_embedding_runtime(tmp_path, dimensions=TEST_DIMS)
    fake.fail_with = RuntimeError("boom")
    indexer = EmbeddingIndexer(runtime)
    await _seed_request("r1")
    with caplog.at_level("WARNING", logger="app.orchestration.indexer"):
        indexer.schedule("prompt", "r1", "text")
        await indexer.wait_idle()  # must not raise
    assert any("Embedding write failed" in r.message for r in caplog.records)
    async with db.session_scope() as session:
        assert await vectors.count_embeddings(session) == 0


async def test_audit_service_notifies_indexer_post_commit(vec_store, tmp_path):
    """The end-to-end hook: record_* -> queue -> batch commit -> embedding."""
    runtime, fake = make_embedding_runtime(tmp_path, dimensions=TEST_DIMS)
    indexer = EmbeddingIndexer(runtime)
    service = AuditService(indexer=indexer)
    service.start()
    try:
        service.record_prompt_request("r1", "the prompt")
        service.record_prompt_response(
            "r1", final_output="the response", model_id="m"
        )
        await service.flush()
        await indexer.wait_idle()
    finally:
        await service.close()

    assert sorted(fake.calls) == [
        "search_document: the prompt",
        "search_document: the response",
    ]
    async with db.session_scope() as session:
        assert await vectors.count_embeddings(session) == 2
