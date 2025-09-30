"""SQLModel table definitions with lazy imports to avoid circular issues."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlmodel import SQLModel

_registry = SQLModel._sa_registry
_registry._class_registry.setdefault("List", list)
_registry._class_registry.setdefault("list", list)

__all__ = [
    "SQLModel",
    "AppSetting",
    "AuditLog",
    "NotificationSetting",
    "PasskeyCredential",
    "PriceHistory",
    "Product",
    "ProductTagLink",
    "ProductURL",
    "Role",
    "SearchCache",
    "Store",
    "Tag",
    "User",
    "UserIdentity",
    "UserRoleAssignment",
]


def __getattr__(name: str) -> object:
    if name == "User":
        from app.models.user import User as _User

        return _User
    if name == "UserRoleAssignment":
        from app.models.user_role_assignment import (
            UserRoleAssignment as _UserRoleAssignment,
        )

        return _UserRoleAssignment
    if name == "Role":
        from app.models.role import Role as _Role

        return _Role
    if name == "UserIdentity":
        from app.models.user_identity import UserIdentity as _UserIdentity

        return _UserIdentity
    if name == "PasskeyCredential":
        from app.models.passkey_credential import (
            PasskeyCredential as _PasskeyCredential,
        )

        return _PasskeyCredential
    if name == "NotificationSetting":
        from app.models.notification_setting import (
            NotificationSetting as _NotificationSetting,
        )

        return _NotificationSetting
    if name == "AuditLog":
        from app.models.audit_log import AuditLog as _AuditLog

        return _AuditLog
    if name == "AppSetting":
        from app.models.app_setting import AppSetting as _AppSetting

        return _AppSetting
    if name == "Product":
        from app.models.product import Product as _Product

        return _Product
    if name == "ProductURL":
        from app.models.product_url import ProductURL as _ProductURL

        return _ProductURL
    if name == "PriceHistory":
        from app.models.price_history import PriceHistory as _PriceHistory

        return _PriceHistory
    if name == "SearchCache":
        from app.models.search_cache import SearchCache as _SearchCache

        return _SearchCache
    if name == "ProductTagLink":
        from app.models.product_tag_link import ProductTagLink as _ProductTagLink

        return _ProductTagLink
    if name == "Store":
        from app.models.store import Store as _Store

        return _Store
    if name == "Tag":
        from app.models.tag import Tag as _Tag

        return _Tag
    raise AttributeError(f"module 'app.models' has no attribute {name!r}")


if TYPE_CHECKING:
    from app.models.app_setting import AppSetting
    from app.models.audit_log import AuditLog
    from app.models.notification_setting import NotificationSetting
    from app.models.passkey_credential import PasskeyCredential
    from app.models.price_history import PriceHistory
    from app.models.product import Product
    from app.models.product_tag_link import ProductTagLink
    from app.models.product_url import ProductURL
    from app.models.role import Role
    from app.models.search_cache import SearchCache
    from app.models.store import Store
    from app.models.tag import Tag
    from app.models.user import User
    from app.models.user_identity import UserIdentity
    from app.models.user_role_assignment import UserRoleAssignment


def ensure_core_model_mappings() -> None:
    """Import core interdependent models to satisfy string relationship targets.

    SQLAlchemy resolves string relationship targets via a registry that
    requires the target classes to be imported (and thus mapped). This function
    eagerly imports the key models with circular references so queries can
    compile even if only a subset of models are referenced by the code path.
    """
    # Import modules (not symbols) to avoid unused import warnings while still
    # ensuring mappers are configured.
    # Import order matters to satisfy interdependent references. Import Role
    # first, then the association table, then User. Also import UserIdentity
    # to cover common auth queries.
    import app.models.role as _role
    import app.models.user as _user
    import app.models.user_identity as _ident
    import app.models.user_role_assignment as _ura

    _ = (_role, _ura, _user, _ident)


# Eagerly ensure mappings whenever app.models is imported to avoid
# first-request mapper initialization errors in development and containers.
ensure_core_model_mappings()
