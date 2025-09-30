from __future__ import annotations

from datetime import datetime
from importlib import import_module
from typing import TYPE_CHECKING

from sqlmodel import Field, Relationship, SQLModel

from app.models.base import utcnow

if TYPE_CHECKING:
    from app.models.role import Role
    from app.models.user import User


class UserRoleAssignment(SQLModel, table=True):
    """Join table linking users to roles with audit metadata."""

    __tablename__ = "user_role_assignments"

    user_id: int = Field(foreign_key="users.id", primary_key=True)
    role_id: int = Field(foreign_key="roles.id", primary_key=True)
    granted_at: datetime = Field(default_factory=utcnow, nullable=False)
    granted_by_id: int | None = Field(default=None, foreign_key="users.id")

    role: "Role" = Relationship(back_populates="assignments")
    user: "User" = Relationship(
        back_populates="role_links",
        sa_relationship_kwargs={"foreign_keys": "UserRoleAssignment.user_id"},
    )
    granted_by: "User" | None = Relationship(
        back_populates="granted_roles",
        sa_relationship_kwargs={"foreign_keys": "UserRoleAssignment.granted_by_id"},
    )


__all__ = ["UserRoleAssignment"]


def _ensure_relationship_dependencies() -> None:
    """Import dependent models so string-based relationships resolve."""

    # Import modules (not symbols) to trigger mapper configuration.
    import_module("app.models.role")
    import_module("app.models.user")


_ensure_relationship_dependencies()


def _register_sqlalchemy_aliases() -> None:
    registry = SQLModel._sa_registry._class_registry
    registry.setdefault("'UserRoleAssignment'", UserRoleAssignment)
    registry.setdefault("'UserRoleAssignment' | None", UserRoleAssignment)


_register_sqlalchemy_aliases()
