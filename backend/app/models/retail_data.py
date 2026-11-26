import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (CheckConstraint, Date, DateTime, ForeignKey,
    ForeignKeyConstraint, Index, Integer, Numeric, String, UniqueConstraint,
    Uuid, func, text)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SalesRecord(Base):
    __tablename__ = "sales_records"
    __table_args__ = (
        CheckConstraint("granularity IN ('TRANSACTION', 'AGGREGATED')", name="ck_sales_granularity"),
        CheckConstraint("(granularity = 'TRANSACTION' AND transaction_id IS NOT NULL AND line_id IS NOT NULL) OR (granularity = 'AGGREGATED' AND aggregate_id IS NOT NULL)", name="ck_sales_identity_by_granularity"),
        UniqueConstraint("company_id", "branch_id", "business_date", "source_upload_id",
                         "granularity", "source_identity", name="uq_sales_upload_source"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    branch_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False, index=True)
    source_upload_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("daily_uploads.id", ondelete="RESTRICT"), nullable=False, index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True)
    recipe_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("recipe_versions.id", ondelete="RESTRICT"), nullable=True, index=True)
    business_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    granularity: Mapped[str] = mapped_column(String(20), nullable=False)
    transaction_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    line_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    aggregate_id: Mapped[str | None] = mapped_column(String(150), nullable=True)
    source_identity: Mapped[str] = mapped_column(String(280), nullable=False)
    transaction_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    net_amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    sales_channel: Mapped[str | None] = mapped_column(String(40), nullable=True)


class InventorySnapshot(Base):
    __tablename__ = "inventory_snapshots"
    __table_args__ = (
        UniqueConstraint("source_upload_id", "product_id", "batch_number",
                         name="uq_inventory_snapshot_upload_batch"),
        UniqueConstraint("id", "source_upload_id", "company_id", "branch_id",
                         "business_date", "product_id", "batch_number",
                         name="uq_inventory_snapshot_coverage_ref"),
        ForeignKeyConstraint(["company_id", "branch_id", "source_upload_id", "business_date"],
            ["daily_uploads.company_id", "daily_uploads.branch_id", "daily_uploads.id", "daily_uploads.business_date"],
            ondelete="RESTRICT", name="fk_inventory_snapshot_upload_scope"),
        ForeignKeyConstraint(["company_id", "product_id"],
            ["products.company_id", "products.id"], ondelete="RESTRICT",
            name="fk_inventory_snapshot_product_company"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    branch_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False, index=True)
    source_upload_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("daily_uploads.id", ondelete="RESTRICT"), nullable=False, index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True)
    business_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    batch_number: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    opening_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    closing_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    unit: Mapped[str] = mapped_column(String(30), nullable=False)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    damaged_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    wasted_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    staff_consumption_quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    adjustment_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    adjustment_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)


class PurchaseLine(Base):
    __tablename__ = "purchase_lines"
    __table_args__ = (
        Index("uq_purchase_legacy_source_line", "source_upload_id", "receipt_id",
              "receipt_line_id", unique=True,
              postgresql_where=text("receipt_identity_id IS NULL"),
              sqlite_where=text("receipt_identity_id IS NULL")),
        Index("uq_purchase_source_receipt_event", "source_upload_id",
              "receipt_identity_id", unique=True,
              postgresql_where=text("receipt_identity_id IS NOT NULL"),
              sqlite_where=text("receipt_identity_id IS NOT NULL")),
        UniqueConstraint("company_id", "branch_id", "source_upload_id",
                         "product_id", "receipt_date", "quantity_received", "purchase_unit", "id",
                         name="uq_purchase_movement_source_ref"),
        UniqueConstraint("receipt_identity_id", "id", name="uq_purchase_identity_line_ref"),
        ForeignKeyConstraint(["company_id", "branch_id", "source_upload_id", "business_date"],
            ["daily_uploads.company_id", "daily_uploads.branch_id", "daily_uploads.id", "daily_uploads.business_date"],
            ondelete="RESTRICT", name="fk_purchase_line_upload_scope"),
        ForeignKeyConstraint(["company_id", "product_id"],
            ["products.company_id", "products.id"], ondelete="RESTRICT",
            name="fk_purchase_line_product_company"),
        ForeignKeyConstraint(["company_id", "branch_id", "receipt_identity_id"],
            ["purchase_receipt_identities.company_id", "purchase_receipt_identities.branch_id",
             "purchase_receipt_identities.id"], ondelete="RESTRICT",
            name="fk_purchase_line_receipt_identity_scope"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    branch_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False, index=True)
    source_upload_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("daily_uploads.id", ondelete="RESTRICT"), nullable=False, index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True)
    receipt_id: Mapped[str] = mapped_column(String(120), nullable=False)
    receipt_line_id: Mapped[str] = mapped_column(String(120), nullable=False)
    business_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    receipt_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    supplier_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    quantity_received: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    unit_purchase_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    purchase_unit: Mapped[str | None] = mapped_column(String(30), nullable=True)
    batch_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    receipt_identity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True, index=True)


class UploadValidationIssue(Base):
    __tablename__ = "upload_validation_issues"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    upload_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("daily_uploads.id", ondelete="CASCADE"), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    sheet: Mapped[str] = mapped_column(String(50), nullable=False)
    row_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    code: Mapped[str] = mapped_column(String(60), nullable=False)
    message: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class HistoricalImportJob(Base):
    __tablename__ = "historical_import_jobs"
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    initiated_by_membership_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("company_memberships.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="QUEUED", server_default="QUEUED")
    total_files: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_files: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    failed_files: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    skipped_files: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    date_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    date_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    branch_ids: Mapped[str] = mapped_column(String(4000), nullable=False, default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class HistoricalImportItem(Base):
    __tablename__ = "historical_import_items"
    __table_args__ = (UniqueConstraint("job_id", "upload_id", name="uq_historical_import_job_upload"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("historical_import_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    upload_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("daily_uploads.id", ondelete="RESTRICT"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="QUEUED", server_default="QUEUED")
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
