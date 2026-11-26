"""additive fields for café workbook v2

Revision ID: 3f011cafe002
Revises: 0b011cafe001
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "3f011cafe002"
down_revision: Union[str, Sequence[str], None] = "0b011cafe001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable fields retain the meaning of all existing v1 and Phase 2 rows.
    op.add_column("sales_records", sa.Column("sales_channel", sa.String(length=40), nullable=True))
    op.add_column("sales_record_modifiers", sa.Column("selection_quantity", sa.Numeric(18, 4), nullable=True))
    op.create_check_constraint(
        "ck_sales_record_modifier_selection_quantity_positive",
        "sales_record_modifiers",
        "selection_quantity IS NULL OR selection_quantity > 0",
    )
    op.add_column("inventory_snapshots", sa.Column("staff_consumption_quantity", sa.Numeric(18, 4), nullable=True))
    op.add_column("purchase_lines", sa.Column("purchase_unit", sa.String(length=30), nullable=True))


def downgrade() -> None:
    op.drop_column("purchase_lines", "purchase_unit")
    op.drop_column("inventory_snapshots", "staff_consumption_quantity")
    op.drop_constraint("ck_sales_record_modifier_selection_quantity_positive", "sales_record_modifiers", type_="check")
    op.drop_column("sales_record_modifiers", "selection_quantity")
    op.drop_column("sales_records", "sales_channel")
