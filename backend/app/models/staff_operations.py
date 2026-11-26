import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (CheckConstraint, DateTime, ForeignKeyConstraint, Index,
    Numeric, String, UniqueConstraint, Uuid, func)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class StockCountSubmission(Base):
    """Immutable operational count submission; it is not an inventory adjustment."""

    __tablename__ = "stock_count_submissions"
    __table_args__ = (
        UniqueConstraint("company_id", "branch_id", "id",
            name="uq_stock_count_company_branch_id"),
        UniqueConstraint("company_id", "branch_id", "idempotency_key",
            name="uq_stock_count_idempotency"),
        UniqueConstraint("company_id", "branch_id", "corrects_submission_id",
            name="uq_stock_count_correction_target"),
        ForeignKeyConstraint(["company_id", "branch_id"],
            ["branches.company_id", "branches.id"], ondelete="RESTRICT",
            name="fk_stock_count_branch_scope"),
        ForeignKeyConstraint(["company_id", "submitted_by_membership_id"],
            ["company_memberships.company_id", "company_memberships.id"],
            ondelete="RESTRICT", name="fk_stock_count_submitter_membership"),
        ForeignKeyConstraint(["company_id", "branch_id", "corrects_submission_id"],
            ["stock_count_submissions.company_id", "stock_count_submissions.branch_id",
             "stock_count_submissions.id"], ondelete="RESTRICT",
            name="fk_stock_count_correction_scope"),
        Index("ix_stock_count_company_branch_counted", "company_id", "branch_id", "counted_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    branch_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    submitted_by_membership_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    idempotency_key: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    counted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
        server_default=func.now(), nullable=False)
    corrects_submission_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)


class StockCountLine(Base):
    __tablename__ = "stock_count_lines"
    __table_args__ = (
        CheckConstraint("quantity >= 0", name="ck_stock_count_quantity_nonnegative"),
        UniqueConstraint("submission_id", "ingredient_product_id", "batch_number",
            name="uq_stock_count_submission_ingredient_batch"),
        ForeignKeyConstraint(["submission_id", "company_id", "branch_id"],
            ["stock_count_submissions.id", "stock_count_submissions.company_id",
             "stock_count_submissions.branch_id"], ondelete="CASCADE",
            name="fk_stock_count_line_submission_scope"),
        ForeignKeyConstraint(["company_id", "ingredient_product_id", "unit"],
            ["products.company_id", "products.id", "products.unit_of_measure"],
            ondelete="RESTRICT", name="fk_stock_count_line_ingredient_unit"),
        Index("ix_stock_count_lines_company_ingredient", "company_id", "ingredient_product_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    submission_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    branch_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    ingredient_product_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    unit: Mapped[str] = mapped_column(String(30), nullable=False)
    batch_number: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")


class PurchaseReceiptConfirmation(Base):
    """Staff audit acknowledgment for a current uploaded receipt line."""

    __tablename__ = "purchase_receipt_confirmations"
    __table_args__ = (
        CheckConstraint("quantity_confirmed > 0", name="ck_receipt_confirmation_quantity_positive"),
        UniqueConstraint("purchase_line_id", name="uq_receipt_confirmation_purchase_line"),
        UniqueConstraint("company_id", "branch_id", "idempotency_key",
            name="uq_receipt_confirmation_idempotency"),
        ForeignKeyConstraint(["company_id", "branch_id", "receipt_identity_id"],
            ["purchase_receipt_identities.company_id", "purchase_receipt_identities.branch_id",
             "purchase_receipt_identities.id"], ondelete="RESTRICT",
            name="fk_receipt_confirmation_identity_scope"),
        ForeignKeyConstraint(["receipt_identity_id", "purchase_line_id"],
            ["purchase_lines.receipt_identity_id", "purchase_lines.id"], ondelete="RESTRICT",
            name="fk_receipt_confirmation_purchase_line"),
        ForeignKeyConstraint(["company_id", "confirmed_by_membership_id"],
            ["company_memberships.company_id", "company_memberships.id"],
            ondelete="RESTRICT", name="fk_receipt_confirmation_actor_scope"),
        ForeignKeyConstraint(["company_id", "ingredient_product_id", "unit"],
            ["products.company_id", "products.id", "products.unit_of_measure"],
            ondelete="RESTRICT", name="fk_receipt_confirmation_ingredient_unit"),
        ForeignKeyConstraint(["company_id", "branch_id"],
            ["branches.company_id", "branches.id"], ondelete="RESTRICT",
            name="fk_receipt_confirmation_branch_scope"),
        Index("ix_receipt_confirmation_company_branch_date", "company_id", "branch_id", "confirmed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    branch_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    receipt_identity_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    purchase_line_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    confirmed_by_membership_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    ingredient_product_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    idempotency_key: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    quantity_confirmed: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    unit: Mapped[str] = mapped_column(String(30), nullable=False)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
        server_default=func.now(), nullable=False)
