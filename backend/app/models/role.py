from typing import TYPE_CHECKING

from sqlalchemy.orm import relationship as sa_relationship
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import IdentifierMixin, TimestampMixin
from app.models.user_role_assignment import UserRoleAssignment

if TYPE_CHECKING:
    from app.models.user import User


class Role(IdentifierMixin, TimestampMixin, SQLModel, table=True):
    __tablename__ = "roles"

    slug: str = Field(index=True, unique=True, nullable=False, max_length=64)
    name: str = Field(nullable=False, max_length=255)
    description: str | None = Field(default=None, max_length=500)

    users: list["User"] = Relationship(
        sa_relationship=sa_relationship(
            "User",
            secondary="user_role_assignments",
            primaryjoin="Role.id == user_role_assignments.c.role_id",
            secondaryjoin="User.id == user_role_assignments.c.user_id",
            back_populates="roles",
            overlaps="role_links,user,assignments,role",
        )
    )
    assignments: list[UserRoleAssignment] = Relationship(
        back_populates="role",
        sa_relationship_kwargs={"overlaps": "users"},
    )


__all__ = ["Role"]


def _register_sqlalchemy_aliases() -> None:
    registry = SQLModel._sa_registry._class_registry
    registry.setdefault("'Role'", Role)
    registry.setdefault("'Role' | None", Role)


_register_sqlalchemy_aliases()
