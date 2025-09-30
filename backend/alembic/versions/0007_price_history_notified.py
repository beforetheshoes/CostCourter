"""Add notified flag to price history entries.

Revision ID: 0007_price_history_notified
Revises: 0006_store_locale_currency
Create Date: 2025-09-27
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0007_price_history_notified"
down_revision = "0006_store_locale_currency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "price_history",
        sa.Column("notified", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column(
        "price_history",
        "notified",
        server_default=None,
    )


def downgrade() -> None:
    op.drop_column("price_history", "notified")
