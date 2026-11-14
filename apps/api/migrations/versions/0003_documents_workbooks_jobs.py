"""documents, workbooks, jobs

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("kind in ('workbook','table')", name="ck_documents_kind"),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name="fk_documents_owner_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_documents"),
    )
    op.create_index("ix_documents_owner_id", "documents", ["owner_id"])
    op.create_table(
        "workbooks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("file_id", sa.Uuid(), nullable=False),
        sa.Column("current_file_id", sa.Uuid(), nullable=True),
        sa.Column("last_saved_seq", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("meta_json", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["id"], ["documents.id"], name="fk_workbooks_id_documents", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name="fk_workbooks_owner_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_workbooks_workspace_id_workspaces",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["file_id"], ["files.id"], name="fk_workbooks_file_id_files", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["current_file_id"],
            ["files.id"],
            name="fk_workbooks_current_file_id_files",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_workbooks"),
        sa.UniqueConstraint("file_id", name="uq_workbooks_file_id"),
    )
    op.create_index("ix_workbooks_owner_id", "workbooks", ["owner_id"])
    op.create_index("ix_workbooks_workspace_id", "workbooks", ["workspace_id"])
    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("progress", sa.Float(), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("result_ref", sa.Text(), nullable=True),
        sa.Column("error_json", postgresql.JSONB(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("kind in ('import','export','operation')", name="ck_jobs_kind"),
        sa.CheckConstraint(
            "status in ('queued','running','succeeded','failed')", name="ck_jobs_status"
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name="fk_jobs_owner_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_jobs"),
    )
    op.create_index("ix_jobs_owner_id", "jobs", ["owner_id"])
    op.create_index("ix_jobs_status_created_at", "jobs", ["status", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_jobs_status_created_at", table_name="jobs")
    op.drop_index("ix_jobs_owner_id", table_name="jobs")
    op.drop_table("jobs")
    op.drop_index("ix_workbooks_workspace_id", table_name="workbooks")
    op.drop_index("ix_workbooks_owner_id", table_name="workbooks")
    op.drop_table("workbooks")
    op.drop_index("ix_documents_owner_id", table_name="documents")
    op.drop_table("documents")
