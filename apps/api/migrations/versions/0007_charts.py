"""charts: definitions attached to a workbook or table document

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "charts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("spec_json", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name="fk_charts_owner_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name="fk_charts_document_id_documents",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_charts"),
    )
    op.create_index("ix_charts_owner_id", "charts", ["owner_id"])
    op.create_index("ix_charts_document_id", "charts", ["document_id"])


def downgrade() -> None:
    op.drop_index("ix_charts_document_id", table_name="charts")
    op.drop_index("ix_charts_owner_id", table_name="charts")
    op.drop_table("charts")
