"""Tests for the sqlite-vec vector store (``app.audit.vectors``).

Runs against the real sqlite-vec extension loaded into the test engine —
these tests are the proof that the extension wiring in ``app.audit.db``
works. Vectors are handcrafted 4-dim unit vectors so distances are obvious.
"""

import pytest
from sqlalchemy import insert, text

from app.audit import db, models, vectors

TEST_DIMS = 4

E1 = [1.0, 0.0, 0.0, 0.0]
E2 = [0.0, 1.0, 0.0, 0.0]
E3 = [0.0, 0.0, 1.0, 0.0]


async def _seed_request(session, request_id: str, prompt: str = "hello"):
    await session.execute(
        insert(models.PromptRequest).values(
            request_id=request_id, raw_prompt=prompt
        )
    )


@pytest.fixture
async def vec_store(audit_db):
    """Migrated database with the vec0 table ensured (skips when the
    sqlite-vec extension cannot load on this Python build)."""
    ready = await vectors.ensure_schema(db.get_engine(), TEST_DIMS)
    if not ready:
        pytest.skip("sqlite-vec extension unavailable on this Python build")
    return audit_db


async def test_extension_loads_and_schema_is_idempotent(vec_store):
    assert db.vec_available()
    # Second call: table exists with matching dims — still usable.
    assert await vectors.ensure_schema(db.get_engine(), TEST_DIMS) is True


async def test_dims_mismatch_disables_store_with_warning(vec_store, caplog):
    with caplog.at_level("WARNING", logger="app.audit.vectors"):
        ready = await vectors.ensure_schema(db.get_engine(), TEST_DIMS + 1)
    assert ready is False
    assert any("EMBEDDING_DIMENSIONS" in r.message for r in caplog.records)


async def test_insert_and_knn_returns_nearest_first(vec_store):
    async with db.session_scope() as session:
        for rid, vec in (("r1", E1), ("r2", E2), ("r3", E3)):
            await _seed_request(session, rid, prompt=f"prompt {rid}")
            assert await vectors.insert_embedding(
                session,
                request_id=rid,
                kind=vectors.KIND_PROMPT,
                model_id="fake",
                vector=vec,
            )
    async with db.session_scope() as session:
        hits = await vectors.knn_search(
            session, vector=[0.9, 0.1, 0.0, 0.0], k=2
        )
    assert [h.request_id for h in hits] == ["r1", "r2"]
    assert hits[0].distance < hits[1].distance
    assert hits[0].kind == vectors.KIND_PROMPT
    assert hits[0].text == "prompt r1"


async def test_duplicate_insert_is_idempotent(vec_store):
    async with db.session_scope() as session:
        await _seed_request(session, "r1")
        assert await vectors.insert_embedding(
            session,
            request_id="r1",
            kind=vectors.KIND_PROMPT,
            model_id="fake",
            vector=E1,
        )
        assert not await vectors.insert_embedding(
            session,
            request_id="r1",
            kind=vectors.KIND_PROMPT,
            model_id="fake",
            vector=E2,
        )
    async with db.session_scope() as session:
        assert await vectors.count_embeddings(session) == 1


async def test_kind_filter_and_response_text_join(vec_store):
    async with db.session_scope() as session:
        await _seed_request(session, "r1", prompt="the prompt text")
        await session.execute(
            insert(models.PromptResponse).values(
                request_id="r1", final_output="the response text"
            )
        )
        await vectors.insert_embedding(
            session,
            request_id="r1",
            kind=vectors.KIND_PROMPT,
            model_id="fake",
            vector=E1,
        )
        await vectors.insert_embedding(
            session,
            request_id="r1",
            kind=vectors.KIND_RESPONSE,
            model_id="fake",
            vector=E2,
        )
    async with db.session_scope() as session:
        responses = await vectors.knn_search(
            session, vector=E1, k=5, kind=vectors.KIND_RESPONSE
        )
        both = await vectors.knn_search(session, vector=E1, k=5)
    assert [h.kind for h in responses] == [vectors.KIND_RESPONSE]
    assert responses[0].text == "the response text"
    assert {h.kind for h in both} == {
        vectors.KIND_PROMPT,
        vectors.KIND_RESPONSE,
    }


async def test_orphan_vector_cleanup(vec_store):
    async with db.session_scope() as session:
        await _seed_request(session, "r1")
        await vectors.insert_embedding(
            session,
            request_id="r1",
            kind=vectors.KIND_PROMPT,
            model_id="fake",
            vector=E1,
        )
    async with db.session_scope() as session:
        # Deleting the request cascades prompt_embeddings but not vec0.
        await session.execute(
            text("DELETE FROM prompt_requests WHERE request_id = 'r1'")
        )
    async with db.session_scope() as session:
        assert await vectors.count_embeddings(session) == 0
        removed = await vectors.delete_orphan_vectors(session)
    assert removed == 1
