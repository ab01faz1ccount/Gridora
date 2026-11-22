"""data_tables.seq_counter: history entries for table operations

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "data_tables",
        sa.Column("seq_counter", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("data_tables", "seq_counter")
