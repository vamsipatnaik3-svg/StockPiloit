"""allow distinct physical receipt events on the same invoice line

Revision ID: 7e010cafe003
Revises: 4c010a9b7d21
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7e010cafe003"
down_revision: Union[str, Sequence[str], None] = "4c010a9b7d21"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Legacy workbooks keep receipt/line uniqueness. Version 3 rows instead
    # use the stable receipt identity, which permits separately received
    # physical deliveries to refer to the same supplier invoice line.
    op.drop_constraint("uq_purchase_source_upload_line", "purchase_lines", type_="unique")
    op.create_index(
        "uq_purchase_legacy_source_line",
        "purchase_lines",
        ["source_upload_id", "receipt_id", "receipt_line_id"],
        unique=True,
        postgresql_where=sa.text("receipt_identity_id IS NULL"),
        sqlite_where=sa.text("receipt_identity_id IS NULL"),
    )
    op.create_index(
        "uq_purchase_source_receipt_event",
        "purchase_lines",
        ["source_upload_id", "receipt_identity_id"],
        unique=True,
        postgresql_where=sa.text("receipt_identity_id IS NOT NULL"),
        sqlite_where=sa.text("receipt_identity_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_purchase_source_receipt_event", table_name="purchase_lines")
    op.drop_index("uq_purchase_legacy_source_line", table_name="purchase_lines")
    bind = op.get_bind()
    duplicate = bind.execute(sa.text(
        "SELECT 1 FROM purchase_lines GROUP BY source_upload_id, receipt_id, receipt_line_id "
        "HAVING count(*) > 1 LIMIT 1"
    )).first()
    if duplicate is not None:
        raise RuntimeError(
            "Cannot downgrade receipt event uniqueness: multiple physical events share an invoice line."
        )
    op.create_unique_constraint("uq_purchase_source_upload_line", "purchase_lines",
        ["source_upload_id", "receipt_id", "receipt_line_id"])
