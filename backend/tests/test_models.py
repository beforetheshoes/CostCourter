from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from textwrap import dedent
from typing import Any, cast

from sqlalchemy import UniqueConstraint

import app.models as models
from app.models.base import BaseTable, TimestampMixin


def test_user_field_constraints() -> None:
    email_field = cast(Any, models.User.model_fields["email"])
    full_name_field = cast(Any, models.User.model_fields["full_name"])

    assert email_field.unique is True
    assert email_field.nullable is False
    assert full_name_field.default is None


def test_product_url_field_defaults() -> None:
    is_primary_field = models.ProductURL.model_fields["is_primary"]
    active_field = models.ProductURL.model_fields["active"]

    assert is_primary_field.default is False
    assert active_field.default is True


def test_store_user_id_and_unique_slug_scope() -> None:
    user_field = cast(Any, models.Store.model_fields["user_id"])
    assert user_field.nullable is False

    table = cast(Any, models.Store).__table__
    constraint_columns = {
        tuple(constraint.columns.keys())
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert ("user_id", "slug") in constraint_columns


def test_tag_user_scoped_uniqueness() -> None:
    user_field = cast(Any, models.Tag.model_fields["user_id"])
    assert user_field.nullable is False

    table = cast(Any, models.Tag).__table__
    constraint_columns = {
        tuple(constraint.columns.keys())
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert ("user_id", "slug") in constraint_columns
    assert ("user_id", "name") in constraint_columns


def test_product_user_scoped_uniqueness() -> None:
    user_field = cast(Any, models.Product.model_fields["user_id"])
    assert user_field.nullable is False

    table = cast(Any, models.Product).__table__
    constraint_columns = {
        tuple(constraint.columns.keys())
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert ("user_id", "slug") in constraint_columns
    assert ("user_id", "name") in constraint_columns


def test_price_history_currency_default() -> None:
    currency_field = models.PriceHistory.model_fields["currency"]
    assert currency_field.default == "USD"


def test_user_identity_uniqueness_and_defaults() -> None:
    provider_field = cast(Any, models.UserIdentity.model_fields["provider"])
    subject_field = cast(Any, models.UserIdentity.model_fields["provider_subject"])
    created_at_field = models.UserIdentity.model_fields["created_at"]

    assert provider_field.nullable is False
    assert subject_field.nullable is False
    assert created_at_field.default_factory is not None


def test_user_identity_enforces_provider_subject_uniqueness() -> None:
    table = cast(Any, models.UserIdentity).__table__
    constraints = {
        tuple(constraint.columns.keys())
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert ("provider", "provider_subject") in constraints


def test_product_tag_link_records_identifiers() -> None:
    product_field = cast(Any, models.ProductTagLink.model_fields["product_id"])
    tag_field = cast(Any, models.ProductTagLink.model_fields["tag_id"])

    assert product_field.primary_key is True
    assert tag_field.primary_key is True


def test_passkey_credential_defaults_and_constraints() -> None:
    assert "PasskeyCredential" in models.__all__
    credential_field = cast(Any, models.PasskeyCredential.model_fields["credential_id"])
    public_key_field = cast(Any, models.PasskeyCredential.model_fields["public_key"])
    sign_count_field = cast(Any, models.PasskeyCredential.model_fields["sign_count"])

    assert credential_field.nullable is False
    assert credential_field.unique is True
    assert public_key_field.nullable is False
    assert sign_count_field.default == 0


def test_timestamp_mixin_touch_updates_timestamp() -> None:
    class Record(TimestampMixin, BaseTable):
        pass

    record = Record()
    previous = record.updated_at
    record.touch()
    assert record.updated_at >= previous


def test_models_module_exports() -> None:
    expected = {
        "AppSetting",
        "AuditLog",
        "SQLModel",
        "NotificationSetting",
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
    }
    assert expected.issubset(set(models.__all__))


def test_role_enforces_unique_slug() -> None:
    slug_field = cast(Any, models.Role.model_fields["slug"])

    assert slug_field.nullable is False
    assert slug_field.unique is True


def test_notification_setting_defaults() -> None:
    enabled_field = models.NotificationSetting.model_fields["enabled"]
    config_field = models.NotificationSetting.model_fields["config"]

    assert enabled_field.default is True
    assert config_field.default is None


def test_price_history_tracks_notification_flag() -> None:
    notified_field = cast(Any, models.PriceHistory.model_fields["notified"])

    assert notified_field.default is False
    assert notified_field.nullable is False


def test_audit_log_fields_allow_optional_actor() -> None:
    actor_field = cast(Any, models.AuditLog.model_fields["actor_id"])
    entity_type_field = cast(Any, models.AuditLog.model_fields["entity_type"])

    assert actor_field.nullable is True
    assert entity_type_field.nullable is True


def test_search_cache_has_unique_hash() -> None:
    query_hash_field = cast(Any, models.SearchCache.model_fields["query_hash"])
    assert query_hash_field.unique is True


def test_user_role_assignment_imports_dependencies_in_isolation() -> None:
    project_root = Path(__file__).resolve().parents[1]
    script = dedent(
        """
        from sqlmodel import SQLModel
        import app.models.user_role_assignment  # triggers dependency imports

        registry = SQLModel._sa_registry._class_registry
        print(int('Role' in registry))
        print(int('User' in registry))
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=True,
    )

    lines = result.stdout.strip().splitlines()
    assert lines == ["1", "1"], result.stdout
