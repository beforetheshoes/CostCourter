from __future__ import annotations

from datetime import datetime

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

from app.models.base import IdentifierMixin, utcnow


class UserIdentity(IdentifierMixin, SQLModel, table=True):
    __tablename__ = "user_identities"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "provider_subject",
            name="uq_user_identities_provider_subject",
        ),
    )

    user_id: int = Field(foreign_key="users.id", nullable=False, index=True)
    provider: str = Field(nullable=False, max_length=64)
    provider_subject: str = Field(nullable=False, max_length=255, index=True)
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
