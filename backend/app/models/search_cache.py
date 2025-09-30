from datetime import datetime

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from app.models.base import IdentifierMixin, TimestampMixin, utcnow


class SearchCache(IdentifierMixin, TimestampMixin, SQLModel, table=True):
    __tablename__ = "search_cache"

    query_hash: str = Field(unique=True, index=True, nullable=False, max_length=64)
    query: str = Field(nullable=False, max_length=1024)
    response: dict[str, object] = Field(sa_column=Column(JSON, nullable=False))
    expires_at: datetime = Field(nullable=False, default_factory=utcnow)


__all__ = ["SearchCache"]
