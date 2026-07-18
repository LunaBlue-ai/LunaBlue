"""Embedding runtime: a second, small llama.cpp model for text embeddings.

Separate instance from the chat model in :mod:`app.llm.runtime` — llama.cpp
instances are single-purpose (a context created for generation cannot also
pool embeddings) and not concurrency-safe, so this runtime owns its own
``Llama`` object and its own lock. Embedding calls therefore never contend
with chat generation.

Unlike the chat model, the embedding model is an enhancement: a missing
model file or an unloadable build logs a warning and leaves the feature
unavailable instead of aborting startup — existing installs without
``models/embedding.gguf`` must keep working.

The default model (nomic-embed-text-v1.5) uses Matryoshka representation
learning: its 768-dim vectors can be truncated to the first N dims and
re-normalized with near-identical retrieval quality. We store 512 dims by
default. nomic also requires task prefixes ("search_document: " for stored
text, "search_query: " for queries) — :meth:`EmbeddingRuntime.embed` applies
them.
"""

import asyncio
import logging
import math
from pathlib import Path
from typing import Any, Callable, Literal

from app.llm import native

logger = logging.getLogger(__name__)

EmbedPrefix = Literal["search_document", "search_query"]

# Character cap per input: nomic's context is 2048 tokens by default here;
# llama.cpp's own truncation behavior varies by version, so cap ourselves.
_MAX_INPUT_CHARS = 8000


def _truncate_normalize(vector: list[float], dims: int) -> list[float]:
    """First ``dims`` components, L2-normalized (Matryoshka truncation)."""
    head = vector[:dims]
    norm = math.sqrt(sum(x * x for x in head))
    if norm == 0.0:
        return head
    return [x / norm for x in head]


class EmbeddingRuntime:
    """Blocking llama.cpp embeddings behind an async lock."""

    def __init__(
        self,
        *,
        model_path: str,
        context_size: int = 2048,
        gpu_layers: int = 0,
        dimensions: int = 512,
        llama_factory: Callable[..., Any] | None = None,
    ) -> None:
        self._model_path = model_path
        self._context_size = context_size
        self._gpu_layers = gpu_layers
        self._dimensions = dimensions
        self._llama_factory = llama_factory
        self._llama: Any | None = None
        self._model_id = Path(model_path).name
        self._lock = asyncio.Lock()
        self._last_error: str | None = None

    def load(self) -> None:
        """Load the embedding model; degrades to unavailable on failure."""
        path = Path(self._model_path)
        if not path.is_file():
            self._last_error = f"model file not found: {self._model_path}"
            logger.warning(
                "Embedding model file not found: %r - embeddings and "
                "/api/search are disabled. Fetch the default model with "
                "scripts/download_embedding_model.ps1 (or .sh), or point "
                "EMBEDDING_MODEL_PATH in .env at an embedding GGUF.",
                self._model_path,
            )
            return
        factory = self._llama_factory
        if factory is None:
            try:
                llama_cpp = native.import_llama()
            except (ImportError, OSError) as exc:
                self._last_error = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "llama-cpp-python failed to load for embeddings (%s) - "
                    "embeddings and /api/search are disabled.",
                    self._last_error,
                )
                return
            factory = llama_cpp.Llama
        try:
            self._llama = factory(
                model_path=str(path),
                n_ctx=self._context_size,
                n_gpu_layers=self._gpu_layers,
                embedding=True,
                verbose=False,
            )
        except Exception as exc:
            self._last_error = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "Embedding model failed to load (%s) - embeddings and "
                "/api/search are disabled.",
                self._last_error,
            )
            return
        self._last_error = None
        logger.info(
            "Embedding model loaded: %s (dims=%d, context_size=%d, "
            "gpu_layers=%d)",
            self._model_id,
            self._dimensions,
            self._context_size,
            self._gpu_layers,
        )

    def close(self) -> None:
        llama, self._llama = self._llama, None
        if llama is not None and hasattr(llama, "close"):
            llama.close()

    @property
    def available(self) -> bool:
        return self._llama is not None

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def dimensions(self) -> int:
        return self._dimensions

    @property
    def model_info(self) -> dict[str, Any]:
        return {
            "model_id": self._model_id,
            "model_path": self._model_path,
            "dimensions": self._dimensions,
            "context_size": self._context_size,
            "gpu_layers": self._gpu_layers,
            "available": self.available,
        }

    async def embed(
        self, texts: list[str], *, prefix: EmbedPrefix
    ) -> list[list[float]]:
        """Embed ``texts`` (order preserved), truncated + L2-normalized.

        Raises RuntimeError when the runtime is unavailable — callers
        (indexer, search route) decide how to degrade.
        """
        if self._llama is None:
            raise RuntimeError(
                "Embedding runtime is not available"
                + (f" ({self._last_error})" if self._last_error else "")
            )
        prefixed = [
            f"{prefix}: {text[:_MAX_INPUT_CHARS]}" for text in texts
        ]
        async with self._lock:
            raw = await asyncio.to_thread(self._embed_blocking, prefixed)
        return [_truncate_normalize(vec, self._dimensions) for vec in raw]

    def _embed_blocking(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            result = self._llama.embed(text)
            # llama_cpp returns one vector per input for pooled models; a
            # per-token matrix (list of lists) means pooling was off - take
            # the mean so the shape stays deterministic.
            if result and isinstance(result[0], (list, tuple)):
                cols = len(result[0])
                result = [
                    sum(row[i] for row in result) / len(result)
                    for i in range(cols)
                ]
            vectors.append([float(x) for x in result])
        return vectors
