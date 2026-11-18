"""history entries and the per-document sequence counter

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workbooks", sa.Column("seq_counter", sa.Integer(), nullable=False, server_default="0")
    )
    op.alter_column("workbooks", "seq_counter", server_default=None)
    op.create_table(
        "history_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("operation_json", postgresql.JSONB(), nullable=False),
        sa.Column("delta_json", postgresql.JSONB(), nullable=False),
        sa.Column("label", sa.String(80), nullable=False),
        sa.Column("undone", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name="fk_history_entries_document_id_documents",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name="fk_history_entries_owner_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_history_entries"),
        sa.UniqueConstraint("document_id", "seq", name="uq_history_entries_document_seq"),
    )
    op.create_index("ix_history_entries_document_id", "history_entries", ["document_id"])
    op.create_index("ix_history_entries_owner_id", "history_entries", ["owner_id"])
    op.create_index("ix_history_entries_document_id_seq", "history_entries", ["document_id", "seq"])


def downgrade() -> None:
    op.drop_index("ix_history_entries_document_id_seq", table_name="history_entries")
    op.drop_index("ix_history_entries_owner_id", table_name="history_entries")
    op.drop_index("ix_history_entries_document_id", table_name="history_entries")
    op.drop_table("history_entries")
    op.drop_column("workbooks", "seq_counter")
