"""Tests for the embedding runtime (``app.llm.embedding``).

All against :class:`tests.backend.fakes.FakeEmbeddingLlama` — the suite
never imports ``llama_cpp``.
"""

import math

import pytest

from app.llm.embedding import EmbeddingRuntime, _truncate_normalize
from tests.backend.fakes import make_embedding_runtime


def test_truncate_normalize_slices_and_unit_norms():
    out = _truncate_normalize([3.0, 4.0, 100.0, 100.0], 2)
    assert out == [0.6, 0.8]
    assert math.isclose(sum(x * x for x in out), 1.0)


def test_truncate_normalize_zero_vector_stays_zero():
    assert _truncate_normalize([0.0, 0.0, 0.0], 2) == [0.0, 0.0]


def test_missing_model_degrades_without_raising(tmp_path, caplog):
    runtime = EmbeddingRuntime(model_path=str(tmp_path / "nope.gguf"))
    with caplog.at_level("WARNING", logger="app.llm.embedding"):
        runtime.load()  # must not raise — embeddings are an enhancement
    assert not runtime.available
    assert "download_embedding_model" in caplog.text
    assert runtime.last_error is not None


async def test_embed_prefixes_truncates_and_normalizes(tmp_path):
    runtime, fake = make_embedding_runtime(tmp_path, dimensions=4)
    assert fake.embedding is True  # loaded with embedding=True
    [vec] = await runtime.embed(["hello world"], prefix="search_document")
    assert len(vec) == 4
    assert math.isclose(sum(x * x for x in vec), 1.0, rel_tol=1e-6)
    assert fake.calls == ["search_document: hello world"]

    [same] = await runtime.embed(["hello world"], prefix="search_document")
    assert same == vec  # deterministic per text

    await runtime.embed(["hello world"], prefix="search_query")
    assert fake.calls[-1] == "search_query: hello world"


async def test_embed_on_unavailable_runtime_raises(tmp_path):
    runtime = EmbeddingRuntime(model_path=str(tmp_path / "nope.gguf"))
    runtime.load()
    with pytest.raises(RuntimeError, match="not available"):
        await runtime.embed(["x"], prefix="search_query")


async def test_per_token_matrix_is_mean_pooled(tmp_path):
    runtime, fake = make_embedding_runtime(tmp_path, dimensions=2)
    # Simulate a build whose embed() returns per-token vectors.
    fake.queued_vectors = [[[2.0, 0.0], [4.0, 0.0]]]
    [vec] = await runtime.embed(["x"], prefix="search_document")
    # Mean [3.0, 0.0] -> normalized [1.0, 0.0].
    assert vec == [1.0, 0.0]


def test_model_info_shape(tmp_path):
    runtime, _ = make_embedding_runtime(tmp_path, dimensions=4, gpu_layers=-1)
    info = runtime.model_info
    assert info["model_id"] == "embedding.gguf"
    assert info["dimensions"] == 4
    assert info["gpu_layers"] == -1
    assert info["available"] is True
    runtime.close()
    assert not runtime.available
