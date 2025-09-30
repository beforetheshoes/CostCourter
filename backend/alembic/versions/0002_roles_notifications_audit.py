"""Add roles, notification settings, audit log, app settings, search cache.

Revision ID: 0002_roles_notifications_audit
Revises: 0001_initial
Create Date: 2025-03-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_roles_notifications_audit"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "roles",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=500)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("slug", name="uq_roles_slug"),
    )
    op.create_index("ix_roles_slug", "roles", ["slug"], unique=False)

    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(length=128), primary_key=True, nullable=False),
        sa.Column("value", sa.String(length=2048)),
        sa.Column("description", sa.String(length=512)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "search_cache",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("query_hash", sa.String(length=64), nullable=False),
        sa.Column("query", sa.String(length=1024), nullable=False),
        sa.Column("response", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("query_hash", name="uq_search_cache_query_hash"),
    )
    op.create_index(
        "ix_search_cache_query_hash", "search_cache", ["query_hash"], unique=False
    )

    op.create_table(
        "notification_settings",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(length=64), nullable=False),
        sa.Column(
            "enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_notification_settings_user_id"
        ),
        sa.UniqueConstraint(
            "user_id", "channel", name="uq_notification_settings_user_channel"
        ),
    )
    op.create_index(
        "ix_notification_settings_user_id",
        "notification_settings",
        ["user_id"],
        unique=False,
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("entity_type", sa.String(length=128)),
        sa.Column("entity_id", sa.String(length=64)),
        sa.Column("ip_address", sa.String(length=64)),
        sa.Column("context", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], name="fk_audit_logs_actor_id"
        ),
    )
    op.create_index("ix_audit_logs_actor_id", "audit_logs", ["actor_id"], unique=False)
    op.create_index(
        "ix_audit_logs_entity_type",
        "audit_logs",
        ["entity_type"],
        unique=False,
    )

    op.create_table(
        "user_role_assignments",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role_id", sa.Integer(), nullable=False),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("granted_by_id", sa.Integer()),
        sa.ForeignKeyConstraint(
            ["role_id"], ["roles.id"], name="fk_user_role_assignments_role_id"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_user_role_assignments_user_id"
        ),
        sa.ForeignKeyConstraint(
            ["granted_by_id"],
            ["users.id"],
            name="fk_user_role_assignments_granted_by_id",
        ),
        sa.PrimaryKeyConstraint("user_id", "role_id", name="pk_user_role_assignments"),
    )
    op.create_index(
        "ix_user_role_assignments_role_id",
        "user_role_assignments",
        ["role_id"],
        unique=False,
    )
    op.create_index(
        "ix_user_role_assignments_user_id",
        "user_role_assignments",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_user_role_assignments_user_id", table_name="user_role_assignments"
    )
    op.drop_index(
        "ix_user_role_assignments_role_id", table_name="user_role_assignments"
    )
    op.drop_table("user_role_assignments")

    op.drop_index("ix_audit_logs_entity_type", table_name="audit_logs")
    op.drop_index("ix_audit_logs_actor_id", table_name="audit_logs")
    op.drop_table("audit_logs")

    op.drop_index(
        "ix_notification_settings_user_id", table_name="notification_settings"
    )
    op.drop_table("notification_settings")

    op.drop_index("ix_search_cache_query_hash", table_name="search_cache")
    op.drop_table("search_cache")

    op.drop_table("app_settings")

    op.drop_index("ix_roles_slug", table_name="roles")
    op.drop_table("roles")
