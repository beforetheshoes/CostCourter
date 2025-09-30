from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import JSON, Column
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import IdentifierMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User


class NotificationSetting(IdentifierMixin, TimestampMixin, SQLModel, table=True):
    __tablename__ = "notification_settings"

    user_id: int = Field(foreign_key="users.id", nullable=False, index=True)
    channel: str = Field(nullable=False, max_length=64)
    enabled: bool = Field(default=True, nullable=False)
    config: dict[str, str | int | float | bool | None] | None = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
    )

    user: "User" = Relationship(back_populates="notification_settings")


__all__ = ["NotificationSetting"]
