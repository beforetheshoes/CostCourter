"""Scope catalog entities to user ownership.

Revision ID: 0003_user_scoped_catalog
Revises: 0002_roles_notifications_audit
Create Date: 2025-02-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_user_scoped_catalog"
down_revision = "0002_roles_notifications_audit"
branch_labels = None
depends_on = None


_USERS = sa.table(
    "users",
    sa.column("id", sa.Integer()),
    sa.column("email", sa.String()),
    sa.column("full_name", sa.String()),
    sa.column("is_active", sa.Boolean()),
    sa.column("is_superuser", sa.Boolean()),
)


def upgrade() -> None:
    op.add_column("stores", sa.Column("user_id", sa.Integer(), nullable=True))
    op.add_column("products", sa.Column("user_id", sa.Integer(), nullable=True))
    op.add_column("tags", sa.Column("user_id", sa.Integer(), nullable=True))

    op.create_index("ix_stores_user_id", "stores", ["user_id"], unique=False)
    op.create_index("ix_products_user_id", "products", ["user_id"], unique=False)
    op.create_index("ix_tags_user_id", "tags", ["user_id"], unique=False)

    op.create_foreign_key(
        "fk_stores_user_id", "stores", "users", ["user_id"], ["id"], ondelete="CASCADE"
    )
    op.create_foreign_key(
        "fk_products_user_id",
        "products",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_tags_user_id", "tags", "users", ["user_id"], ["id"], ondelete="CASCADE"
    )

    op.drop_constraint("uq_products_name", "products", type_="unique")
    op.drop_constraint("uq_products_slug", "products", type_="unique")
    op.drop_constraint("uq_tags_name", "tags", type_="unique")
    op.drop_constraint("uq_tags_slug", "tags", type_="unique")
    op.drop_constraint("uq_stores_slug", "stores", type_="unique")

    connection = op.get_bind()
    owner_id = connection.execute(sa.select(sa.func.min(_USERS.c.id))).scalar()
    if owner_id is None:
        result = connection.execute(
            sa.insert(_USERS)
            .values(
                email="system@costcourter.dev",
                full_name="System",
                is_active=True,
                is_superuser=True,
            )
            .returning(_USERS.c.id)
        )
        owner_id = result.scalar_one()

    for table_name in ("stores", "products", "tags"):
        table = sa.table(table_name, sa.column("user_id", sa.Integer()))
        connection.execute(
            sa.update(table).where(table.c.user_id.is_(None)).values(user_id=owner_id)
        )

    op.alter_column("stores", "user_id", existing_type=sa.Integer(), nullable=False)
    op.alter_column("products", "user_id", existing_type=sa.Integer(), nullable=False)
    op.alter_column("tags", "user_id", existing_type=sa.Integer(), nullable=False)

    op.create_unique_constraint(
        "uq_products_user_slug", "products", ["user_id", "slug"]
    )
    op.create_unique_constraint(
        "uq_products_user_name", "products", ["user_id", "name"]
    )
    op.create_unique_constraint("uq_tags_user_slug", "tags", ["user_id", "slug"])
    op.create_unique_constraint("uq_tags_user_name", "tags", ["user_id", "name"])
    op.create_unique_constraint("uq_stores_user_slug", "stores", ["user_id", "slug"])


def downgrade() -> None:
    op.drop_constraint("uq_stores_user_slug", "stores", type_="unique")
    op.drop_constraint("uq_tags_user_name", "tags", type_="unique")
    op.drop_constraint("uq_tags_user_slug", "tags", type_="unique")
    op.drop_constraint("uq_products_user_name", "products", type_="unique")
    op.drop_constraint("uq_products_user_slug", "products", type_="unique")

    op.alter_column("tags", "user_id", existing_type=sa.Integer(), nullable=True)
    op.alter_column("products", "user_id", existing_type=sa.Integer(), nullable=True)
    op.alter_column("stores", "user_id", existing_type=sa.Integer(), nullable=True)

    op.drop_constraint("fk_tags_user_id", "tags", type_="foreignkey")
    op.drop_constraint("fk_products_user_id", "products", type_="foreignkey")
    op.drop_constraint("fk_stores_user_id", "stores", type_="foreignkey")

    op.drop_index("ix_tags_user_id", table_name="tags")
    op.drop_index("ix_products_user_id", table_name="products")
    op.drop_index("ix_stores_user_id", table_name="stores")

    op.drop_column("tags", "user_id")
    op.drop_column("products", "user_id")
    op.drop_column("stores", "user_id")

    op.create_unique_constraint("uq_stores_slug", "stores", ["slug"])
    op.create_unique_constraint("uq_tags_slug", "tags", ["slug"])
    op.create_unique_constraint("uq_tags_name", "tags", ["name"])
    op.create_unique_constraint("uq_products_slug", "products", ["slug"])
    op.create_unique_constraint("uq_products_name", "products", ["name"])
