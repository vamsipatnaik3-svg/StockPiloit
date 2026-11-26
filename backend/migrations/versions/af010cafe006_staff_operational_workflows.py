"""add auditable stock counts, receipt confirmations, and event timestamps

Revision ID: af010cafe006
Revises: 9f010cafe005
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "af010cafe006"
down_revision: Union[str, Sequence[str], None] = "9f010cafe005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing movement timestamps remain NULL. New event times are written only
    # by workflows that receive an explicit timestamp from the operator.
    op.add_column("stock_movements",
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_stock_movement_company_branch_occurred", "stock_movements",
        ["company_id", "branch_id", "occurred_at"], unique=False)

    op.create_table(
        "stock_count_submissions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("branch_id", sa.Uuid(), nullable=False),
        sa.Column("submitted_by_membership_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("counted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False),
        sa.Column("corrects_submission_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["company_id", "branch_id"],
            ["branches.company_id", "branches.id"], ondelete="RESTRICT",
            name="fk_stock_count_branch_scope"),
        sa.ForeignKeyConstraint(["company_id", "submitted_by_membership_id"],
            ["company_memberships.company_id", "company_memberships.id"],
            ondelete="RESTRICT", name="fk_stock_count_submitter_membership"),
        sa.ForeignKeyConstraint(["company_id", "branch_id", "corrects_submission_id"],
            ["stock_count_submissions.company_id", "stock_count_submissions.branch_id",
             "stock_count_submissions.id"], ondelete="RESTRICT",
            name="fk_stock_count_correction_scope"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "branch_id", "id",
            name="uq_stock_count_company_branch_id"),
        sa.UniqueConstraint("company_id", "branch_id", "idempotency_key",
            name="uq_stock_count_idempotency"),
        sa.UniqueConstraint("company_id", "branch_id", "corrects_submission_id",
            name="uq_stock_count_correction_target"),
    )
    op.create_index("ix_stock_count_company_branch_counted", "stock_count_submissions",
        ["company_id", "branch_id", "counted_at"], unique=False)

    op.create_table(
        "stock_count_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("submission_id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("branch_id", sa.Uuid(), nullable=False),
        sa.Column("ingredient_product_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("unit", sa.String(length=30), nullable=False),
        sa.Column("batch_number", sa.String(length=120), server_default="", nullable=False),
        sa.CheckConstraint("quantity >= 0", name="ck_stock_count_quantity_nonnegative"),
        sa.ForeignKeyConstraint(["submission_id", "company_id", "branch_id"],
            ["stock_count_submissions.id", "stock_count_submissions.company_id",
             "stock_count_submissions.branch_id"], ondelete="CASCADE",
            name="fk_stock_count_line_submission_scope"),
        sa.ForeignKeyConstraint(["company_id", "ingredient_product_id", "unit"],
            ["products.company_id", "products.id", "products.unit_of_measure"],
            ondelete="RESTRICT", name="fk_stock_count_line_ingredient_unit"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("submission_id", "ingredient_product_id", "batch_number",
            name="uq_stock_count_submission_ingredient_batch"),
    )
    op.create_index("ix_stock_count_lines_company_ingredient", "stock_count_lines",
        ["company_id", "ingredient_product_id"], unique=False)

    op.create_table(
        "purchase_receipt_confirmations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("branch_id", sa.Uuid(), nullable=False),
        sa.Column("receipt_identity_id", sa.Uuid(), nullable=False),
        sa.Column("purchase_line_id", sa.Uuid(), nullable=False),
        sa.Column("confirmed_by_membership_id", sa.Uuid(), nullable=False),
        sa.Column("ingredient_product_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("quantity_confirmed", sa.Numeric(18, 4), nullable=False),
        sa.Column("unit", sa.String(length=30), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("quantity_confirmed > 0",
            name="ck_receipt_confirmation_quantity_positive"),
        sa.ForeignKeyConstraint(["company_id", "branch_id", "receipt_identity_id"],
            ["purchase_receipt_identities.company_id", "purchase_receipt_identities.branch_id",
             "purchase_receipt_identities.id"], ondelete="RESTRICT",
            name="fk_receipt_confirmation_identity_scope"),
        sa.ForeignKeyConstraint(["receipt_identity_id", "purchase_line_id"],
            ["purchase_lines.receipt_identity_id", "purchase_lines.id"], ondelete="RESTRICT",
            name="fk_receipt_confirmation_purchase_line"),
        sa.ForeignKeyConstraint(["company_id", "confirmed_by_membership_id"],
            ["company_memberships.company_id", "company_memberships.id"],
            ondelete="RESTRICT", name="fk_receipt_confirmation_actor_scope"),
        sa.ForeignKeyConstraint(["company_id", "ingredient_product_id", "unit"],
            ["products.company_id", "products.id", "products.unit_of_measure"],
            ondelete="RESTRICT", name="fk_receipt_confirmation_ingredient_unit"),
        sa.ForeignKeyConstraint(["company_id", "branch_id"],
            ["branches.company_id", "branches.id"], ondelete="RESTRICT",
            name="fk_receipt_confirmation_branch_scope"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("purchase_line_id",
            name="uq_receipt_confirmation_purchase_line"),
        sa.UniqueConstraint("company_id", "branch_id", "idempotency_key",
            name="uq_receipt_confirmation_idempotency"),
    )
    op.create_index("ix_receipt_confirmation_company_branch_date",
        "purchase_receipt_confirmations", ["company_id", "branch_id", "confirmed_at"],
        unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    checks = (
        ("purchase_receipt_confirmations", "SELECT 1 FROM purchase_receipt_confirmations LIMIT 1"),
        ("stock_count_submissions", "SELECT 1 FROM stock_count_submissions LIMIT 1"),
        ("stock movement event timestamps",
         "SELECT 1 FROM stock_movements WHERE occurred_at IS NOT NULL LIMIT 1"),
    )
    for label, query in checks:
        if bind.execute(sa.text(query)).first() is not None:
            raise RuntimeError(f"Cannot downgrade while {label} audit data exists.")

    op.drop_index("ix_receipt_confirmation_company_branch_date",
        table_name="purchase_receipt_confirmations")
    op.drop_table("purchase_receipt_confirmations")
    op.drop_index("ix_stock_count_lines_company_ingredient", table_name="stock_count_lines")
    op.drop_table("stock_count_lines")
    op.drop_index("ix_stock_count_company_branch_counted",
        table_name="stock_count_submissions")
    op.drop_table("stock_count_submissions")
    op.drop_index("ix_stock_movement_company_branch_occurred", table_name="stock_movements")
    op.drop_column("stock_movements", "occurred_at")
