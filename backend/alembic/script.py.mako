"""${message}"""

revision = ${repr(revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}

from alembic import op
import sqlalchemy as sa
import sqlmodel


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
