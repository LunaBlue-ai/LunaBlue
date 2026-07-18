"""Semantic search over stored prompts and responses (sqlite-vec KNN).

The query text is embedded on the dedicated embedding runtime (never
contending with chat generation) and matched against the vectors the
:class:`~app.orchestration.indexer.EmbeddingIndexer` stored for audited
prompt/response rows.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request

from app.api.errors import ApiError
from app.api.schemas.search import SearchResponse, SearchResult
from app.audit import db, vectors
from app.llm.embedding import EmbeddingRuntime

router = APIRouter()

_TEXT_PREVIEW_CHARS = 500

_UNAVAILABLE = (
    "Semantic search is unavailable: the embedding runtime is not loaded. "
    "Fetch the embedding model with scripts/download_embedding_model.ps1 "
    "(or .sh) and restart, or set EMBEDDING_ENABLED=false to silence this."
)


def get_embedding_runtime(request: Request) -> EmbeddingRuntime | None:
    """FastAPI dependency: the embedding runtime, or None when disabled."""
    return getattr(request.app.state, "embedding_runtime", None)


@router.get(
    "/search",
    response_model=SearchResponse,
    summary="Semantic search over stored prompts and responses",
    description=(
        "Embeds the query text and returns the nearest stored prompt/"
        "response embeddings by L2 distance (unit vectors: smaller is more "
        "similar). Only turns persisted to the audit store are searchable; "
        "run the backfill script to index history from before embeddings "
        "were enabled."
    ),
    responses={
        503: {"description": "Embedding runtime or vector store unavailable."}
    },
)
async def search(
    runtime: Annotated[EmbeddingRuntime | None, Depends(get_embedding_runtime)],
    q: Annotated[
        str, Query(min_length=1, max_length=2000, description="Query text.")
    ],
    limit: Annotated[
        int, Query(ge=1, le=50, description="Maximum results to return.")
    ] = 10,
    kind: Annotated[
        Literal["all", "prompt", "response"],
        Query(description="Restrict matches to prompts or responses."),
    ] = "all",
) -> SearchResponse:
    if runtime is None or not runtime.available or not db.vec_available():
        raise ApiError(
            503, code="embeddings_unavailable", message=_UNAVAILABLE
        )
    [vector] = await runtime.embed([q], prefix="search_query")
    async with db.session_scope() as session:
        hits = await vectors.knn_search(
            session,
            vector=vector,
            k=limit,
            kind=None if kind == "all" else kind,
        )
    return SearchResponse(
        query=q,
        results=[
            SearchResult(
                request_id=hit.request_id,
                session_id=hit.session_id,
                kind=hit.kind,
                distance=hit.distance,
                text=hit.text[:_TEXT_PREVIEW_CHARS],
                timestamp=hit.timestamp,
            )
            for hit in hits
        ],
    )
