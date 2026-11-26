"""add structured retail data and upload processing fields

Revision ID: 5fa5d29bb64c
Revises: 601f1d6e5bef
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "5fa5d29bb64c"
down_revision: Union[str, Sequence[str], None] = "601f1d6e5bef"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("daily_uploads", sa.Column("checksum_sha256", sa.String(64), nullable=True))
    op.add_column("daily_uploads", sa.Column("processing_status", sa.String(30), server_default="QUEUED", nullable=False))
    op.add_column("daily_uploads", sa.Column("processing_version", sa.Integer(), server_default="1", nullable=False))
    for name in ("rows_read", "rows_accepted", "rows_rejected", "warning_count", "error_count"):
        op.add_column("daily_uploads", sa.Column(name, sa.Integer(), server_default="0", nullable=False))
    op.add_column("daily_uploads", sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("daily_uploads", sa.Column("processing_completed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_daily_uploads_checksum_sha256", "daily_uploads", ["checksum_sha256"])
    op.create_index("uq_daily_upload_current_branch_date", "daily_uploads", ["branch_id", "business_date"], unique=True, sqlite_where=sa.text("is_current = 1"), postgresql_where=sa.text("is_current = true"))

    op.create_table("product_categories",
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "name", name="uq_product_category_company_name"))
    op.create_index("ix_product_categories_company_id", "product_categories", ["company_id"])
    op.create_table("products",
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("company_id", sa.Uuid(), nullable=False), sa.Column("category_id", sa.Uuid(), nullable=True),
        sa.Column("sku", sa.String(100), nullable=False), sa.Column("product_name", sa.String(200), nullable=False), sa.Column("brand", sa.String(100), nullable=True),
        sa.Column("unit_of_measure", sa.String(30), nullable=False), sa.Column("barcode", sa.String(100), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["category_id"], ["product_categories.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("company_id", "sku", name="uq_product_company_sku"))
    op.create_index("ix_products_company_id", "products", ["company_id"])

    op.create_table("sales_records",
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("company_id", sa.Uuid(), nullable=False), sa.Column("branch_id", sa.Uuid(), nullable=False),
        sa.Column("source_upload_id", sa.Uuid(), nullable=False), sa.Column("product_id", sa.Uuid(), nullable=False), sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("granularity", sa.String(20), nullable=False), sa.Column("transaction_id", sa.String(120), nullable=True), sa.Column("line_id", sa.String(120), nullable=True),
        sa.Column("aggregate_id", sa.String(150), nullable=True), sa.Column("source_identity", sa.String(280), nullable=False), sa.Column("transaction_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("quantity", sa.Numeric(18,4), nullable=False), sa.Column("unit_price", sa.Numeric(18,4), nullable=False), sa.Column("discount_amount", sa.Numeric(18,4), nullable=False),
        sa.Column("tax_amount", sa.Numeric(18,4), nullable=False), sa.Column("net_amount", sa.Numeric(18,4), nullable=False),
        sa.CheckConstraint("granularity IN ('TRANSACTION', 'AGGREGATED')", name="ck_sales_granularity"),
        sa.CheckConstraint("(granularity = 'TRANSACTION' AND transaction_id IS NOT NULL AND line_id IS NOT NULL) OR (granularity = 'AGGREGATED' AND aggregate_id IS NOT NULL)", name="ck_sales_identity_by_granularity"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_upload_id"], ["daily_uploads.id"], ondelete="RESTRICT"), sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("company_id", "branch_id", "business_date", "granularity", "source_identity", name="uq_sales_business_source"))
    for table, cols in (("sales_records", ["company_id", "branch_id", "source_upload_id", "product_id", "business_date"]),):
        for col in cols: op.create_index(f"ix_{table}_{col}", table, [col])

    op.create_table("inventory_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("company_id", sa.Uuid(), nullable=False), sa.Column("branch_id", sa.Uuid(), nullable=False),
        sa.Column("source_upload_id", sa.Uuid(), nullable=False), sa.Column("product_id", sa.Uuid(), nullable=False), sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("batch_number", sa.String(120), server_default="", nullable=False), sa.Column("opening_quantity", sa.Numeric(18,4), nullable=False), sa.Column("closing_quantity", sa.Numeric(18,4), nullable=False),
        sa.Column("unit", sa.String(30), nullable=False), sa.Column("expiry_date", sa.Date(), nullable=True), sa.Column("unit_cost", sa.Numeric(18,4), nullable=True),
        sa.Column("damaged_quantity", sa.Numeric(18,4), server_default="0", nullable=False), sa.Column("wasted_quantity", sa.Numeric(18,4), server_default="0", nullable=False),
        sa.Column("adjustment_quantity", sa.Numeric(18,4), server_default="0", nullable=False), sa.Column("adjustment_reason", sa.String(300), nullable=True),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_upload_id"], ["daily_uploads.id"], ondelete="RESTRICT"), sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("company_id", "branch_id", "business_date", "product_id", "batch_number", name="uq_inventory_snapshot_batch"))
    for col in ["company_id", "branch_id", "source_upload_id", "product_id", "business_date"]: op.create_index(f"ix_inventory_snapshots_{col}", "inventory_snapshots", [col])

    op.create_table("purchase_lines",
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("company_id", sa.Uuid(), nullable=False), sa.Column("branch_id", sa.Uuid(), nullable=False),
        sa.Column("source_upload_id", sa.Uuid(), nullable=False), sa.Column("product_id", sa.Uuid(), nullable=False), sa.Column("receipt_id", sa.String(120), nullable=False),
        sa.Column("receipt_line_id", sa.String(120), nullable=False), sa.Column("receipt_date", sa.Date(), nullable=False), sa.Column("supplier_name", sa.String(200), nullable=True),
        sa.Column("quantity_received", sa.Numeric(18,4), nullable=False), sa.Column("unit_purchase_price", sa.Numeric(18,4), nullable=True),
        sa.Column("batch_number", sa.String(120), nullable=True), sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_upload_id"], ["daily_uploads.id"], ondelete="RESTRICT"), sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("company_id", "branch_id", "receipt_id", "receipt_line_id", name="uq_purchase_source_line"))
    for col in ["company_id", "branch_id", "source_upload_id", "product_id", "receipt_date"]: op.create_index(f"ix_purchase_lines_{col}", "purchase_lines", [col])

    op.create_table("upload_validation_issues",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False), sa.Column("upload_id", sa.Uuid(), nullable=False), sa.Column("severity", sa.String(10), nullable=False),
        sa.Column("sheet", sa.String(50), nullable=False), sa.Column("row_number", sa.Integer(), nullable=True), sa.Column("code", sa.String(60), nullable=False),
        sa.Column("message", sa.String(500), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["upload_id"], ["daily_uploads.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("id"))
    op.create_index("ix_upload_validation_issues_upload_id", "upload_validation_issues", ["upload_id"])

    op.create_table("historical_import_jobs",
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("initiated_by_membership_id", sa.Uuid(), nullable=False), sa.Column("status", sa.String(20), server_default="QUEUED", nullable=False),
        sa.Column("total_files", sa.Integer(), nullable=False), sa.Column("completed_files", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failed_files", sa.Integer(), server_default="0", nullable=False), sa.Column("date_start", sa.Date(), nullable=True),
        sa.Column("date_end", sa.Date(), nullable=True), sa.Column("branch_ids", sa.String(4000), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True), sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["initiated_by_membership_id"], ["company_memberships.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"))
    op.create_index("ix_historical_import_jobs_company_id", "historical_import_jobs", ["company_id"])
    op.create_table("historical_import_items",
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("upload_id", sa.Uuid(), nullable=False), sa.Column("status", sa.String(20), server_default="QUEUED", nullable=False),
        sa.Column("error_message", sa.String(500), nullable=True), sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["historical_import_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["upload_id"], ["daily_uploads.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("job_id", "upload_id", name="uq_historical_import_job_upload"))
    op.create_index("ix_historical_import_items_job_id", "historical_import_items", ["job_id"])
    op.create_index("ix_historical_import_items_upload_id", "historical_import_items", ["upload_id"])


def downgrade() -> None:
    op.drop_index("ix_historical_import_items_upload_id", table_name="historical_import_items")
    op.drop_index("ix_historical_import_items_job_id", table_name="historical_import_items")
    op.drop_table("historical_import_items")
    op.drop_index("ix_historical_import_jobs_company_id", table_name="historical_import_jobs")
    op.drop_table("historical_import_jobs")
    for table, cols in (("upload_validation_issues", ["upload_id"]), ("purchase_lines", ["company_id", "branch_id", "source_upload_id", "product_id", "receipt_date"]), ("inventory_snapshots", ["company_id", "branch_id", "source_upload_id", "product_id", "business_date"]), ("sales_records", ["company_id", "branch_id", "source_upload_id", "product_id", "business_date"])):
        for col in cols: op.drop_index(f"ix_{table}_{col}", table_name=table)
        op.drop_table(table)
    op.drop_index("ix_products_company_id", table_name="products")
    op.drop_table("products")
    op.drop_index("ix_product_categories_company_id", table_name="product_categories")
    op.drop_table("product_categories")
    op.drop_index("uq_daily_upload_current_branch_date", table_name="daily_uploads")
    op.drop_index("ix_daily_uploads_checksum_sha256", table_name="daily_uploads")
    for name in ("processing_completed_at", "processing_started_at", "error_count", "warning_count", "rows_rejected", "rows_accepted", "rows_read", "processing_version", "processing_status", "checksum_sha256"):
        op.drop_column("daily_uploads", name)
