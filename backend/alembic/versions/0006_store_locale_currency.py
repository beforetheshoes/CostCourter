"""Add locale and currency columns to stores.

Revision ID: 0006_store_locale_currency
Revises: 0005_product_metadata
Create Date: 2025-09-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_store_locale_currency"
down_revision = "0005_product_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "stores",
        sa.Column("locale", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "stores",
        sa.Column("currency", sa.String(length=12), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("stores", "currency")
    op.drop_column("stores", "locale")
