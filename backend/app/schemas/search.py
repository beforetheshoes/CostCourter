from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SearchResult(BaseModel):
    """Normalized representation of a single SearXNG search hit."""

    title: str | None = None
    url: str
    snippet: str | None = None
    thumbnail: str | None = None
    domain: str | None = None
    relevance: int = Field(ge=0)
    engine: str | None = None
    score: float | None = None
    store_id: int | None = None
    store_name: str | None = None


class SearchResponse(BaseModel):
    """Payload returned by the search endpoint."""

    query: str
    cache_hit: bool
    expires_at: datetime | None = None
    results: list[SearchResult] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "query": "buy noise cancelling headphones",
                    "cache_hit": False,
                    "results": [
                        {
                            "title": "Noise Cancelling Headphones",
                            "url": "https://example.com/headphones",
                            "snippet": "Premium wireless headphones...",
                            "thumbnail": "https://example.com/image.jpg",
                            "domain": "example.com",
                            "relevance": 0,
                            "engine": "google",
                            "score": 12.5,
                            "store_id": 42,
                            "store_name": "Example Store",
                        }
                    ],
                }
            ]
        }
    )
