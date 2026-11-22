"""data_tables: metadata and the current-version pointer of Data Tables

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "data_tables",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("meta_json", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["id"], ["documents.id"], name="fk_data_tables_id_documents", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name="fk_data_tables_owner_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_data_tables_workspace_id_workspaces",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_data_tables"),
    )
    op.create_index("ix_data_tables_owner_id", "data_tables", ["owner_id"])
    op.create_index("ix_data_tables_workspace_id", "data_tables", ["workspace_id"])


def downgrade() -> None:
    op.drop_index("ix_data_tables_workspace_id", table_name="data_tables")
    op.drop_index("ix_data_tables_owner_id", table_name="data_tables")
    op.drop_table("data_tables")
