"""scope sales source uniqueness to an upload version

Revision ID: 8e010cafe004
Revises: 7e010cafe003
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "8e010cafe004"
down_revision: Union[str, Sequence[str], None] = "7e010cafe003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Historical corrections may contain the same source row identity in
    # different uploads. Include the immutable upload version in the key.
    # Existing rows remain untouched; the old key was stricter, so all
    # existing data also satisfies the new constraint.
    op.drop_constraint("uq_sales_business_source", "sales_records", type_="unique")
    op.create_unique_constraint(
        "uq_sales_upload_source",
        "sales_records",
        ["company_id", "branch_id", "business_date", "source_upload_id",
         "granularity", "source_identity"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    duplicate = bind.execute(sa.text(
        "SELECT 1 FROM sales_records "
        "GROUP BY company_id, branch_id, business_date, granularity, source_identity "
        "HAVING count(*) > 1 LIMIT 1"
    )).first()
    if duplicate is not None:
        raise RuntimeError(
            "Cannot downgrade sales retention: historical upload versions contain "
            "the same sales source identity."
        )
    op.drop_constraint("uq_sales_upload_source", "sales_records", type_="unique")
    op.create_unique_constraint(
        "uq_sales_business_source",
        "sales_records",
        ["company_id", "branch_id", "business_date", "granularity", "source_identity"],
    )
