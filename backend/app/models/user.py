from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy.orm import relationship as sa_relationship
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import IdentifierMixin, TimestampMixin
from app.models.user_role_assignment import UserRoleAssignment

if TYPE_CHECKING:
    from app.models.audit_log import AuditLog
    from app.models.notification_setting import NotificationSetting
    from app.models.passkey_credential import PasskeyCredential
    from app.models.product import Product
    from app.models.product_url import ProductURL
    from app.models.role import Role
    from app.models.store import Store
    from app.models.tag import Tag
    from app.models.user_role_assignment import UserRoleAssignment


class User(IdentifierMixin, TimestampMixin, SQLModel, table=True):
    __tablename__ = "users"

    email: str = Field(index=True, unique=True, nullable=False)
    full_name: str | None = Field(default=None, max_length=255)
    is_active: bool = Field(default=True)
    is_superuser: bool = Field(default=False)
    last_login_at: datetime | None = Field(default=None)

    passkeys: list["PasskeyCredential"] = Relationship(back_populates="user")
    product_urls: list["ProductURL"] = Relationship(back_populates="created_by")
    notification_settings: list["NotificationSetting"] = Relationship(
        back_populates="user"
    )
    stores: list["Store"] = Relationship(back_populates="owner")
    products: list["Product"] = Relationship(back_populates="owner")
    tags: list["Tag"] = Relationship(back_populates="owner")
    roles: list["Role"] = Relationship(
        sa_relationship=sa_relationship(
            "Role",
            secondary="user_role_assignments",
            primaryjoin="User.id == user_role_assignments.c.user_id",
            secondaryjoin="Role.id == user_role_assignments.c.role_id",
            back_populates="users",
            overlaps="user,role_links,assignments,role",
        )
    )
    role_links: list["UserRoleAssignment"] = Relationship(
        back_populates="user",
        sa_relationship_kwargs={
            "foreign_keys": "UserRoleAssignment.user_id",
            "primaryjoin": "User.id == UserRoleAssignment.user_id",
            "overlaps": "roles",
        },
    )
    granted_roles: list["UserRoleAssignment"] = Relationship(
        back_populates="granted_by",
        sa_relationship_kwargs={
            "foreign_keys": "UserRoleAssignment.granted_by_id",
            "primaryjoin": "User.id == UserRoleAssignment.granted_by_id",
            "overlaps": "roles,role_links",
        },
    )
    audit_logs: list["AuditLog"] = Relationship(back_populates="actor")


def _ensure_relationship_dependencies() -> None:
    import app.models.audit_log as _audit
    import app.models.notification_setting as _notification
    import app.models.passkey_credential as _passkey
    import app.models.product as _product
    import app.models.product_url as _product_url
    import app.models.role as _role
    import app.models.store as _store
    import app.models.tag as _tag
    import app.models.user_role_assignment as _user_role

    _ = (
        _passkey,
        _notification,
        _role,
        _user_role,
        _audit,
        _product_url,
        _product,
        _store,
        _tag,
    )


_ensure_relationship_dependencies()


def _register_sqlalchemy_aliases() -> None:
    registry = SQLModel._sa_registry._class_registry
    registry.setdefault("'User'", User)
    registry.setdefault("'User' | None", User)


_register_sqlalchemy_aliases()
