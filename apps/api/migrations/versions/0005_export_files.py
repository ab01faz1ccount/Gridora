"""files.kind accepts 'export' (generated downloads)

Revision ID: 0005
Revises: 0004
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_files_kind", "files", type_="check")
    op.create_check_constraint(
        "ck_files_kind", "files", "kind in ('workbook','table','original','export')"
    )


def downgrade() -> None:
    op.execute("DELETE FROM files WHERE kind = 'export'")
    op.drop_constraint("ck_files_kind", "files", type_="check")
    op.create_check_constraint("ck_files_kind", "files", "kind in ('workbook','table','original')")
