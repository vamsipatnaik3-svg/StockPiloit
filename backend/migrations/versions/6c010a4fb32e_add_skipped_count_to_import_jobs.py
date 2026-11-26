"""track skipped imports and scope purchases by business date

Revision ID: 6c010a4fb32e
Revises: 5fa5d29bb64c
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "6c010a4fb32e"
down_revision: Union[str, Sequence[str], None] = "5fa5d29bb64c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("historical_import_jobs", sa.Column(
        "skipped_files", sa.Integer(), server_default="0", nullable=False
    ))
    op.add_column("purchase_lines", sa.Column("business_date", sa.Date(), nullable=True))
    op.execute(
        "UPDATE purchase_lines SET business_date = ("
        "SELECT daily_uploads.business_date FROM daily_uploads "
        "WHERE daily_uploads.id = purchase_lines.source_upload_id) "
        "WHERE business_date IS NULL"
    )
    op.execute("UPDATE purchase_lines SET business_date = receipt_date WHERE business_date IS NULL")
    op.alter_column("purchase_lines", "business_date", nullable=False)
    op.drop_constraint("uq_purchase_source_line", "purchase_lines", type_="unique")
    op.create_unique_constraint("uq_purchase_source_line", "purchase_lines",
        ["company_id", "branch_id", "business_date", "receipt_id", "receipt_line_id"])
    op.create_index("ix_purchase_lines_business_date", "purchase_lines", ["business_date"])


def downgrade() -> None:
    op.drop_index("ix_purchase_lines_business_date", table_name="purchase_lines")
    op.drop_constraint("uq_purchase_source_line", "purchase_lines", type_="unique")
    op.create_unique_constraint("uq_purchase_source_line", "purchase_lines",
        ["company_id", "branch_id", "receipt_id", "receipt_line_id"])
    op.drop_column("purchase_lines", "business_date")
    op.drop_column("historical_import_jobs", "skipped_files")
