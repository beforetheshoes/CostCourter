"""Add store metadata fields for domains and scraping strategy.

Revision ID: 0004_store_metadata
Revises: 0003_user_scoped_catalog
Create Date: 2025-03-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_store_metadata"
down_revision = "0003_user_scoped_catalog"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "stores",
        sa.Column(
            "domains",
            sa.JSON(),
            nullable=True,
        ),
    )
    op.add_column(
        "stores",
        sa.Column(
            "scrape_strategy",
            sa.JSON(),
            nullable=True,
        ),
    )
    op.add_column(
        "stores",
        sa.Column(
            "settings",
            sa.JSON(),
            nullable=True,
        ),
    )
    op.add_column("stores", sa.Column("notes", sa.Text(), nullable=True))

    connection = op.get_bind()
    dialect = connection.dialect.name
    if dialect == "postgresql":
        connection.execute(
            sa.text("UPDATE stores SET domains = '[]'::jsonb WHERE domains IS NULL")
        )
        connection.execute(
            sa.text(
                "UPDATE stores SET scrape_strategy = '{}'::jsonb "
                "WHERE scrape_strategy IS NULL"
            )
        )
        connection.execute(
            sa.text("UPDATE stores SET settings = '{}'::jsonb WHERE settings IS NULL")
        )
    else:
        connection.execute(
            sa.text("UPDATE stores SET domains = '[]' WHERE domains IS NULL")
        )
        connection.execute(
            sa.text(
                "UPDATE stores SET scrape_strategy = '{}' WHERE scrape_strategy IS NULL"
            )
        )
        connection.execute(
            sa.text("UPDATE stores SET settings = '{}' WHERE settings IS NULL")
        )

    op.alter_column("stores", "domains", existing_type=sa.JSON(), nullable=False)
    op.alter_column(
        "stores", "scrape_strategy", existing_type=sa.JSON(), nullable=False
    )
    op.alter_column("stores", "settings", existing_type=sa.JSON(), nullable=False)


def downgrade() -> None:
    op.drop_column("stores", "notes")
    op.drop_column("stores", "settings")
    op.drop_column("stores", "scrape_strategy")
    op.drop_column("stores", "domains")
