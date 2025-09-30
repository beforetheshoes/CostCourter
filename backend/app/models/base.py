from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(UTC)


class TimestampMixin(SQLModel, table=False):
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=utcnow, nullable=False)


class IdentifierMixin(SQLModel, table=False):
    id: int | None = Field(default=None, primary_key=True)


class BaseTable(SQLModel, table=False):
    """Base class for SQLModel tables with timestamp helpers."""

    def touch(self) -> None:
        self.updated_at = utcnow()
