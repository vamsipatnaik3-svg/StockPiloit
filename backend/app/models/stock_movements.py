import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (CheckConstraint, Date, DateTime, ForeignKeyConstraint,
    Index, Numeric, String, UniqueConstraint, Uuid, column, func, literal, text)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class StockMovementReasonCode(Base):
    __tablename__ = "stock_movement_reason_codes"
    __table_args__ = (
        CheckConstraint(
            "movement_type IN ('PURCHASE_RECEIPT','OTHER_INFLOW','POSITIVE_ADJUSTMENT',"
            "'TRANSFER_IN','WASTE','STAFF_CONSUMPTION','DAMAGE','NEGATIVE_ADJUSTMENT',"
            "'OTHER_OUTFLOW','TRANSFER_OUT')",
            name="ck_stock_movement_reason_type",
        ),
    )

    code: Mapped[str] = mapped_column(String(60), primary_key=True)
    movement_type: Mapped[str] = mapped_column(String(30), primary_key=True)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False, server_default="true")


class PurchaseReceiptIdentity(Base):
    __tablename__ = "purchase_receipt_identities"
    __table_args__ = (
        UniqueConstraint("company_id", "branch_id", "receipt_event_id",
                         name="uq_purchase_receipt_event_scope"),
        UniqueConstraint("company_id", "branch_id", "id",
                         name="uq_purchase_receipt_identity_scope"),
        ForeignKeyConstraint(["company_id", "branch_id"],
            ["branches.company_id", "branches.id"], ondelete="RESTRICT",
            name="fk_purchase_receipt_identity_branch_scope"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    branch_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    receipt_event_id: Mapped[str] = mapped_column(String(150), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class PurchaseReceiptCurrentLine(Base):
    __tablename__ = "purchase_receipt_current_lines"
    __table_args__ = (
        UniqueConstraint("purchase_line_id", name="uq_purchase_receipt_current_line"),
        ForeignKeyConstraint(["company_id", "branch_id", "receipt_identity_id"],
            ["purchase_receipt_identities.company_id", "purchase_receipt_identities.branch_id",
             "purchase_receipt_identities.id"], ondelete="CASCADE",
            name="fk_purchase_current_identity_scope"),
        ForeignKeyConstraint(["receipt_identity_id", "purchase_line_id"],
            ["purchase_lines.receipt_identity_id", "purchase_lines.id"], ondelete="RESTRICT",
            name="fk_purchase_current_line_identity"),
    )

    receipt_identity_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    branch_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    purchase_line_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class StockTransfer(Base):
    __tablename__ = "stock_transfers"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_stock_transfer_quantity_positive"),
        CheckConstraint("source_branch_id <> destination_branch_id", name="ck_stock_transfer_distinct_branches"),
        UniqueConstraint("id", "company_id", "ingredient_product_id", "movement_date",
                         "quantity", "unit", name="uq_stock_transfer_movement_ref"),
        ForeignKeyConstraint(["company_id", "source_branch_id"],
            ["branches.company_id", "branches.id"], ondelete="RESTRICT",
            name="fk_stock_transfer_source_branch"),
        ForeignKeyConstraint(["company_id", "destination_branch_id"],
            ["branches.company_id", "branches.id"], ondelete="RESTRICT",
            name="fk_stock_transfer_destination_branch"),
        ForeignKeyConstraint(["company_id", "ingredient_product_id", "unit"],
            ["products.company_id", "products.id", "products.unit_of_measure"],
            ondelete="RESTRICT", name="fk_stock_transfer_ingredient_unit"),
        ForeignKeyConstraint(["company_id", "created_by_user_id"],
            ["company_memberships.company_id", "company_memberships.user_id"],
            ondelete="RESTRICT", name="fk_stock_transfer_creator_membership"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    ingredient_product_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    source_branch_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    destination_branch_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    movement_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    unit: Mapped[str] = mapped_column(String(30), nullable=False)
    source_batch_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    destination_batch_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class StockMovement(Base):
    __tablename__ = "stock_movements"
    __table_args__ = (
        CheckConstraint(
            "movement_type IN ('PURCHASE_RECEIPT','OTHER_INFLOW','POSITIVE_ADJUSTMENT',"
            "'TRANSFER_IN','WASTE','STAFF_CONSUMPTION','DAMAGE','NEGATIVE_ADJUSTMENT',"
            "'OTHER_OUTFLOW','TRANSFER_OUT')",
            name="ck_stock_movement_type",
        ),
        CheckConstraint("quantity > 0", name="ck_stock_movement_quantity_positive"),
        CheckConstraint("origin_type IN ('UPLOAD','MANUAL')", name="ck_stock_movement_origin_type"),
        CheckConstraint(
            "(origin_type = 'UPLOAD' AND source_upload_id IS NOT NULL) OR "
            "(origin_type = 'MANUAL' AND source_upload_id IS NULL AND created_by_user_id IS NOT NULL)",
            name="ck_stock_movement_origin_source",
        ),
        CheckConstraint(
            "(movement_type = 'PURCHASE_RECEIPT' AND purchase_line_id IS NOT NULL AND source_upload_id IS NOT NULL) OR "
            "(movement_type <> 'PURCHASE_RECEIPT' AND purchase_line_id IS NULL)",
            name="ck_stock_movement_purchase_link",
        ),
        CheckConstraint(
            "(movement_type IN ('TRANSFER_IN','TRANSFER_OUT') AND transfer_id IS NOT NULL) OR "
            "(movement_type NOT IN ('TRANSFER_IN','TRANSFER_OUT') AND transfer_id IS NULL)",
            name="ck_stock_movement_transfer_link",
        ),
        CheckConstraint(
            "movement_type NOT IN ('POSITIVE_ADJUSTMENT','NEGATIVE_ADJUSTMENT') OR reason_code IS NOT NULL",
            name="ck_stock_movement_adjustment_reason_required",
        ),
        CheckConstraint(
            "origin_type <> 'MANUAL' OR reason_code IS NOT NULL",
            name="ck_stock_movement_manual_reason_required",
        ),
        CheckConstraint(
            "(voided_at IS NULL AND voided_by_user_id IS NULL AND void_reason IS NULL) OR "
            "(voided_at IS NOT NULL AND voided_by_user_id IS NOT NULL AND length(trim(void_reason)) > 0)",
            name="ck_stock_movement_void_audit_complete",
        ),
        CheckConstraint("origin_type = 'MANUAL' OR voided_at IS NULL",
                        name="ck_stock_movement_upload_not_voidable"),
        UniqueConstraint("purchase_line_id", name="uq_stock_movement_purchase_line"),
        UniqueConstraint("transfer_id", "movement_type", name="uq_stock_movement_transfer_leg"),
        ForeignKeyConstraint(["company_id", "branch_id"],
            ["branches.company_id", "branches.id"], ondelete="RESTRICT",
            name="fk_stock_movement_branch_scope"),
        ForeignKeyConstraint(["company_id", "ingredient_product_id", "unit"],
            ["products.company_id", "products.id", "products.unit_of_measure"],
            ondelete="RESTRICT", name="fk_stock_movement_ingredient_unit"),
        ForeignKeyConstraint(["company_id", "branch_id", "source_upload_id"],
            ["daily_uploads.company_id", "daily_uploads.branch_id", "daily_uploads.id"],
            ondelete="RESTRICT", name="fk_stock_movement_source_upload_scope"),
        ForeignKeyConstraint(["company_id", "branch_id", "source_upload_id",
            "ingredient_product_id", "movement_date", "quantity", "unit", "purchase_line_id"],
            ["purchase_lines.company_id", "purchase_lines.branch_id", "purchase_lines.source_upload_id",
             "purchase_lines.product_id", "purchase_lines.receipt_date", "purchase_lines.quantity_received",
             "purchase_lines.purchase_unit", "purchase_lines.id"],
            ondelete="RESTRICT", name="fk_stock_movement_purchase_source"),
        ForeignKeyConstraint(["transfer_id", "company_id", "ingredient_product_id",
            "movement_date", "quantity", "unit"],
            ["stock_transfers.id", "stock_transfers.company_id", "stock_transfers.ingredient_product_id",
             "stock_transfers.movement_date", "stock_transfers.quantity", "stock_transfers.unit"],
            ondelete="RESTRICT", name="fk_stock_movement_transfer_event"),
        ForeignKeyConstraint(["reason_code", "movement_type"],
            ["stock_movement_reason_codes.code", "stock_movement_reason_codes.movement_type"],
            ondelete="RESTRICT", name="fk_stock_movement_reason_type"),
        ForeignKeyConstraint(["company_id", "created_by_user_id"],
            ["company_memberships.company_id", "company_memberships.user_id"],
            ondelete="RESTRICT", name="fk_stock_movement_creator_membership"),
        ForeignKeyConstraint(["company_id", "voided_by_user_id"],
            ["company_memberships.company_id", "company_memberships.user_id"],
            ondelete="RESTRICT", name="fk_stock_movement_void_actor_membership"),
        Index("uq_stock_movement_upload_event", "source_upload_id", "physical_event_id",
              "ingredient_product_id", func.coalesce(column("batch_number"), literal("")),
              unique=True, postgresql_where=text("source_upload_id IS NOT NULL"),
              sqlite_where=text("source_upload_id IS NOT NULL")),
        Index("uq_stock_movement_manual_event", "company_id", "branch_id", "physical_event_id",
              "ingredient_product_id", func.coalesce(column("batch_number"), literal("")),
              unique=True, postgresql_where=text("source_upload_id IS NULL"),
              sqlite_where=text("source_upload_id IS NULL")),
        Index("ix_stock_movement_company_branch_date", "company_id", "branch_id", "movement_date"),
        Index("ix_stock_movement_company_branch_occurred", "company_id", "branch_id", "occurred_at"),
        Index("ix_stock_movement_company_ingredient_date", "company_id", "ingredient_product_id", "movement_date"),
        Index("ix_stock_movements_company_id", "company_id"),
        Index("ix_stock_movements_branch_id", "branch_id"),
        Index("ix_stock_movements_ingredient_product_id", "ingredient_product_id"),
        Index("ix_stock_movements_movement_date", "movement_date"),
        Index("ix_stock_movements_source_upload_id", "source_upload_id"),
        Index("ix_stock_movements_purchase_line_id", "purchase_line_id"),
        Index("ix_stock_movements_transfer_id", "transfer_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    branch_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    ingredient_product_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    movement_date: Mapped[date] = mapped_column(Date, nullable=False)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    movement_type: Mapped[str] = mapped_column(String(30), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    unit: Mapped[str] = mapped_column(String(30), nullable=False)
    batch_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source_upload_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    purchase_line_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    transfer_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    origin_type: Mapped[str] = mapped_column(String(20), nullable=False)
    physical_event_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source_reference: Mapped[str | None] = mapped_column(String(150), nullable=True)
    reason_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    reason_detail: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    voided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    void_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)


class StockCoverageDeclaration(Base):
    __tablename__ = "stock_coverage_declarations"
    __table_args__ = (
        CheckConstraint(
            "coverage_dimension IN ('INGREDIENT','BATCH','OPENING_STOCK','CLOSING_STOCK','MOVEMENT_CATEGORY')",
            name="ck_stock_coverage_dimension",
        ),
        CheckConstraint("scope_type IN ('INGREDIENT','ALL_BATCHES','BATCH')", name="ck_stock_coverage_scope_type"),
        CheckConstraint(
            "status IN ('COMPLETE','PARTIAL','UNREPORTED','NOT_APPLICABLE','NO_STOCK')",
            name="ck_stock_coverage_status",
        ),
        CheckConstraint(
            "(scope_type = 'BATCH' AND batch_number IS NOT NULL) OR "
            "(scope_type <> 'BATCH' AND batch_number IS NULL)",
            name="ck_stock_coverage_batch_scope",
        ),
        CheckConstraint(
            "(coverage_dimension = 'MOVEMENT_CATEGORY' AND movement_type IS NOT NULL) OR "
            "(coverage_dimension <> 'MOVEMENT_CATEGORY' AND movement_type IS NULL)",
            name="ck_stock_coverage_movement_type",
        ),
        CheckConstraint(
            "status <> 'NO_STOCK' OR coverage_dimension IN ('INGREDIENT','BATCH','OPENING_STOCK','CLOSING_STOCK')",
            name="ck_stock_coverage_no_stock_dimension",
        ),
        CheckConstraint(
            "coverage_dimension <> 'INGREDIENT' OR scope_type = 'INGREDIENT'",
            name="ck_stock_coverage_ingredient_scope",
        ),
        CheckConstraint(
            "coverage_dimension <> 'BATCH' OR scope_type = 'ALL_BATCHES'",
            name="ck_stock_coverage_batch_dimension_scope",
        ),
        ForeignKeyConstraint(["company_id", "branch_id", "source_upload_id", "business_date"],
            ["daily_uploads.company_id", "daily_uploads.branch_id", "daily_uploads.id", "daily_uploads.business_date"],
            ondelete="RESTRICT", name="fk_stock_coverage_upload_scope"),
        ForeignKeyConstraint(["company_id", "ingredient_product_id", "unit"],
            ["products.company_id", "products.id", "products.unit_of_measure"],
            ondelete="RESTRICT", name="fk_stock_coverage_ingredient_unit"),
        ForeignKeyConstraint(["inventory_snapshot_id", "source_upload_id", "company_id",
            "branch_id", "business_date", "ingredient_product_id", "batch_number"],
            ["inventory_snapshots.id", "inventory_snapshots.source_upload_id", "inventory_snapshots.company_id",
             "inventory_snapshots.branch_id", "inventory_snapshots.business_date",
             "inventory_snapshots.product_id", "inventory_snapshots.batch_number"],
            ondelete="RESTRICT", name="fk_stock_coverage_inventory_snapshot"),
        Index("uq_stock_coverage_declaration_scope", "source_upload_id", "ingredient_product_id",
              "coverage_dimension", "scope_type", func.coalesce(column("batch_number"), literal("")),
              func.coalesce(column("movement_type"), literal("")), unique=True),
        Index("ix_stock_coverage_declarations_company_id", "company_id"),
        Index("ix_stock_coverage_declarations_branch_id", "branch_id"),
        Index("ix_stock_coverage_declarations_source_upload_id", "source_upload_id"),
        Index("ix_stock_coverage_declarations_ingredient_product_id", "ingredient_product_id"),
        Index("ix_stock_coverage_company_branch_date", "company_id", "branch_id", "business_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    branch_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    business_date: Mapped[date] = mapped_column(Date, nullable=False)
    source_upload_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    ingredient_product_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    unit: Mapped[str] = mapped_column(String(30), nullable=False)
    coverage_dimension: Mapped[str] = mapped_column(String(30), nullable=False)
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False)
    batch_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    movement_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    inventory_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
