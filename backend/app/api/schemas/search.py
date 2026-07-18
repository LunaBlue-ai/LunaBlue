"""Response schemas for the semantic search endpoint."""

from datetime import datetime

from pydantic import BaseModel, Field


class SearchResult(BaseModel):
    """One nearest-neighbor hit over the stored embeddings."""

    request_id: str
    session_id: str | None = None
    kind: str = Field(description='"prompt" or "response"')
    distance: float = Field(
        description="L2 distance between the query and the stored vector "
        "(vectors are unit-normalized, so smaller is more similar; 0 is "
        "identical)."
    )
    text: str = Field(description="The matched stored text (truncated).")
    timestamp: datetime | None = None


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]
