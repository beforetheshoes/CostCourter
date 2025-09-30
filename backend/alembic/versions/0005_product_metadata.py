"""Add product metadata fields and cached price aggregates.

Revision ID: 0005_product_metadata
Revises: 0004_store_metadata
Create Date: 2025-03-05
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_product_metadata"
down_revision = "0004_store_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'published'"),
        ),
    )
    op.add_column(
        "products",
        sa.Column(
            "favourite",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "products",
        sa.Column(
            "only_official",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "products",
        sa.Column("notify_price", sa.Float(), nullable=True),
    )
    op.add_column(
        "products",
        sa.Column("notify_percent", sa.Float(), nullable=True),
    )
    op.add_column(
        "products",
        sa.Column("current_price", sa.Float(), nullable=True),
    )
    op.add_column(
        "products",
        sa.Column("price_cache", sa.JSON(), nullable=True),
    )
    op.add_column(
        "products",
        sa.Column("ignored_urls", sa.JSON(), nullable=True),
    )
    op.add_column(
        "products",
        sa.Column("image_url", sa.String(length=1024), nullable=True),
    )

    connection = op.get_bind()
    dialect = connection.dialect.name

    if dialect == "postgresql":
        connection.execute(
            sa.text(
                "UPDATE products SET price_cache = '[]'::jsonb WHERE price_cache IS NULL"
            )
        )
        connection.execute(
            sa.text(
                "UPDATE products SET ignored_urls = '[]'::jsonb WHERE ignored_urls IS NULL"
            )
        )
    else:
        connection.execute(
            sa.text("UPDATE products SET price_cache = '[]' WHERE price_cache IS NULL")
        )
        connection.execute(
            sa.text(
                "UPDATE products SET ignored_urls = '[]' WHERE ignored_urls IS NULL"
            )
        )

    connection.execute(
        sa.text("UPDATE products SET status = 'published' WHERE status IS NULL")
    )
    connection.execute(
        sa.text("UPDATE products SET favourite = true WHERE favourite IS NULL")
    )
    connection.execute(
        sa.text("UPDATE products SET only_official = false WHERE only_official IS NULL")
    )

    op.alter_column("products", "price_cache", existing_type=sa.JSON(), nullable=False)
    op.alter_column("products", "ignored_urls", existing_type=sa.JSON(), nullable=False)


def downgrade() -> None:
    op.drop_column("products", "image_url")
    op.drop_column("products", "ignored_urls")
    op.drop_column("products", "price_cache")
    op.drop_column("products", "current_price")
    op.drop_column("products", "notify_percent")
    op.drop_column("products", "notify_price")
    op.drop_column("products", "only_official")
    op.drop_column("products", "favourite")
    op.drop_column("products", "status")
