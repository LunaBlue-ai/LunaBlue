"""Tests for GET /api/search (semantic search over stored embeddings)."""

import pytest
from sqlalchemy import insert

from app.audit import db, models, vectors
from tests.backend.fakes import (
    FakeAuditService,
    FakeLlamaRuntime,
    make_client,
    make_embedding_runtime,
)

TEST_DIMS = 4


@pytest.fixture
async def vec_store(audit_db):
    ready = await vectors.ensure_schema(db.get_engine(), TEST_DIMS)
    if not ready:
        pytest.skip("sqlite-vec extension unavailable on this Python build")
    return audit_db


async def _seed(request_id: str, prompt: str, vector: list[float]) -> None:
    async with db.session_scope() as session:
        await session.execute(
            insert(models.PromptRequest).values(
                request_id=request_id, session_id=None, raw_prompt=prompt
            )
        )
        await vectors.insert_embedding(
            session,
            request_id=request_id,
            kind=vectors.KIND_PROMPT,
            model_id="fake",
            vector=vector,
        )


async def test_search_returns_ranked_results(vec_store, tmp_path):
    runtime, fake = make_embedding_runtime(tmp_path, dimensions=TEST_DIMS)
    await _seed("near", "close prompt", [1.0, 0.0, 0.0, 0.0])
    await _seed("far", "distant prompt", [0.0, 0.0, 0.0, 1.0])
    # The query embeds to (almost) the "near" vector.
    fake.queued_vectors = [[0.9, 0.1, 0.0, 0.0]]

    runtime_fake = FakeLlamaRuntime()
    runtime_fake.load()
    client = make_client(
        FakeAuditService(), runtime_fake, embedding_runtime=runtime
    )
    async with client:
        response = await client.get(
            "/api/search", params={"q": "something close"}
        )
    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "something close"
    ids = [r["request_id"] for r in body["results"]]
    assert ids == ["near", "far"]
    assert body["results"][0]["distance"] < body["results"][1]["distance"]
    assert body["results"][0]["kind"] == "prompt"
    assert body["results"][0]["text"] == "close prompt"
    # The query was embedded with the search_query prefix.
    assert fake.calls[-1] == "search_query: something close"


async def test_search_kind_filter_and_limit(vec_store, tmp_path):
    runtime, fake = make_embedding_runtime(tmp_path, dimensions=TEST_DIMS)
    await _seed("p1", "prompt one", [1.0, 0.0, 0.0, 0.0])
    fake.queued_vectors = [[1.0, 0.0, 0.0, 0.0], [1.0, 0.0, 0.0, 0.0]]

    runtime_fake = FakeLlamaRuntime()
    runtime_fake.load()
    client = make_client(
        FakeAuditService(), runtime_fake, embedding_runtime=runtime
    )
    async with client:
        responses_only = await client.get(
            "/api/search", params={"q": "x", "kind": "response"}
        )
        bad_limit = await client.get(
            "/api/search", params={"q": "x", "limit": 0}
        )
    assert responses_only.status_code == 200
    assert responses_only.json()["results"] == []
    assert bad_limit.status_code == 422


async def test_search_503_when_embeddings_unavailable(vec_store):
    runtime_fake = FakeLlamaRuntime()
    runtime_fake.load()
    client = make_client(
        FakeAuditService(), runtime_fake, embedding_runtime=None
    )
    async with client:
        response = await client.get("/api/search", params={"q": "x"})
    assert response.status_code == 503
    body = response.json()
    assert body["code"] == "embeddings_unavailable"
