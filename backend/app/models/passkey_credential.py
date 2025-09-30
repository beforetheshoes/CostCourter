from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Column, DateTime, event
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import IdentifierMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User


class PasskeyCredential(IdentifierMixin, TimestampMixin, SQLModel, table=True):
    __tablename__ = "passkey_credentials"

    user_id: int = Field(foreign_key="users.id", nullable=False, index=True)
    credential_id: str = Field(nullable=False, unique=True, max_length=255)
    public_key: str = Field(nullable=False)
    aaguid: str | None = Field(default=None, max_length=36)
    nickname: str | None = Field(default=None, max_length=255)
    transports: str | None = Field(default=None, max_length=255)
    sign_count: int = Field(default=0, nullable=False)
    backup_eligible: bool = Field(default=False, nullable=False)
    backup_state: bool = Field(default=False, nullable=False)
    last_used_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True))
    )

    user: "User" = Relationship(back_populates="passkeys")


def _ensure_relationship_dependencies() -> None:
    import app.models.user as _user

    _ = _user


_ensure_relationship_dependencies()


@event.listens_for(PasskeyCredential, "load")
def _attach_timezone_on_load(target: PasskeyCredential, _: Any) -> None:
    if target.last_used_at is not None and target.last_used_at.tzinfo is None:
        target.last_used_at = target.last_used_at.replace(tzinfo=UTC)
