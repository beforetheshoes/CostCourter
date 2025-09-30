from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import JSON, Column
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import IdentifierMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User


class AuditLog(IdentifierMixin, TimestampMixin, SQLModel, table=True):
    __tablename__ = "audit_logs"

    actor_id: int | None = Field(
        default=None,
        foreign_key="users.id",
        index=True,
        nullable=True,
    )
    action: str = Field(nullable=False, max_length=128)
    entity_type: str | None = Field(
        default=None,
        max_length=128,
        index=True,
        nullable=True,
    )
    entity_id: str | None = Field(default=None, max_length=64)
    ip_address: str | None = Field(default=None, max_length=64)
    context: dict[str, object] | None = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
    )

    actor: "User" | None = Relationship(back_populates="audit_logs")


__all__ = ["AuditLog"]
