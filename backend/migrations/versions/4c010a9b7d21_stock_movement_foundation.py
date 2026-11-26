"""add source-versioned stock movement foundation

Revision ID: 4c010a9b7d21
Revises: 3f011cafe002
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "4c010a9b7d21"
down_revision: Union[str, Sequence[str], None] = "3f011cafe002"
branch_labels = None
depends_on = None


MOVEMENT_TYPES = (
    "PURCHASE_RECEIPT", "OTHER_INFLOW", "POSITIVE_ADJUSTMENT", "TRANSFER_IN",
    "WASTE", "STAFF_CONSUMPTION", "DAMAGE", "NEGATIVE_ADJUSTMENT",
    "OTHER_OUTFLOW", "TRANSFER_OUT",
)

REASONS = (
    ("RECEIVED_FROM_SUPPLIER", "PURCHASE_RECEIPT", "Received from supplier"),
    ("OTHER_INFLOW_REASON", "OTHER_INFLOW", "Other stock inflow"),
    ("POSITIVE_COUNT_CORRECTION", "POSITIVE_ADJUSTMENT", "Positive count correction"),
    ("POSITIVE_ADJUSTMENT_OTHER", "POSITIVE_ADJUSTMENT", "Other positive adjustment"),
    ("TRANSFER_IN_REASON", "TRANSFER_IN", "Branch transfer received"),
    ("WASTE_SPOILAGE", "WASTE", "Spoilage"),
    ("WASTE_PREPARATION", "WASTE", "Preparation waste"),
    ("WASTE_OTHER", "WASTE", "Other waste"),
    ("STAFF_MEAL", "STAFF_CONSUMPTION", "Staff meal"),
    ("STAFF_DRINK", "STAFF_CONSUMPTION", "Staff drink"),
    ("STAFF_CONSUMPTION_OTHER", "STAFF_CONSUMPTION", "Other staff consumption"),
    ("DAMAGE_STORAGE", "DAMAGE", "Damaged in storage"),
    ("DAMAGE_HANDLING", "DAMAGE", "Damaged in handling"),
    ("DAMAGE_OTHER", "DAMAGE", "Other damage"),
    ("NEGATIVE_COUNT_CORRECTION", "NEGATIVE_ADJUSTMENT", "Negative count correction"),
    ("NEGATIVE_SHRINKAGE", "NEGATIVE_ADJUSTMENT", "Shrinkage adjustment"),
    ("NEGATIVE_ADJUSTMENT_OTHER", "NEGATIVE_ADJUSTMENT", "Other negative adjustment"),
    ("OTHER_OUTFLOW_REASON", "OTHER_OUTFLOW", "Other stock outflow"),
    ("TRANSFER_OUT_REASON", "TRANSFER_OUT", "Branch transfer sent"),
)


def upgrade() -> None:
    # Composite target keys allow new rows to enforce same-company relationships.
    op.create_unique_constraint("uq_branch_company_id_id", "branches", ["company_id", "id"])
    op.create_unique_constraint("uq_product_company_id_unit", "products",
        ["company_id", "id", "unit_of_measure"])
    op.create_unique_constraint("uq_product_company_id", "products", ["company_id", "id"])
    op.create_unique_constraint("uq_daily_upload_company_branch_id", "daily_uploads",
        ["company_id", "branch_id", "id"])
    op.create_unique_constraint("uq_daily_upload_company_branch_id_date", "daily_uploads",
        ["company_id", "branch_id", "id", "business_date"])

    # Keep old rows, but scope uniqueness to the exact upload version.
    op.drop_constraint("uq_inventory_snapshot_batch", "inventory_snapshots", type_="unique")
    op.create_unique_constraint("uq_inventory_snapshot_upload_batch", "inventory_snapshots",
        ["source_upload_id", "product_id", "batch_number"])
    op.create_unique_constraint("uq_inventory_snapshot_coverage_ref", "inventory_snapshots",
        ["id", "source_upload_id", "company_id", "branch_id", "business_date",
         "product_id", "batch_number"])
    op.create_foreign_key("fk_inventory_snapshot_upload_scope", "inventory_snapshots",
        "daily_uploads", ["company_id", "branch_id", "source_upload_id", "business_date"],
        ["company_id", "branch_id", "id", "business_date"], ondelete="RESTRICT")
    op.create_foreign_key("fk_inventory_snapshot_product_company", "inventory_snapshots",
        "products", ["company_id", "product_id"], ["company_id", "id"], ondelete="RESTRICT")

    op.drop_constraint("uq_purchase_source_line", "purchase_lines", type_="unique")
    op.create_unique_constraint("uq_purchase_source_upload_line", "purchase_lines",
        ["source_upload_id", "receipt_id", "receipt_line_id"])
    op.add_column("purchase_lines", sa.Column("receipt_identity_id", sa.Uuid(), nullable=True))
    op.create_index("ix_purchase_lines_receipt_identity_id", "purchase_lines", ["receipt_identity_id"])
    op.create_unique_constraint("uq_purchase_identity_line_ref", "purchase_lines",
        ["receipt_identity_id", "id"])
    op.create_unique_constraint("uq_purchase_movement_source_ref", "purchase_lines",
        ["company_id", "branch_id", "source_upload_id", "product_id", "receipt_date",
         "quantity_received", "purchase_unit", "id"])
    op.create_foreign_key("fk_purchase_line_upload_scope", "purchase_lines", "daily_uploads",
        ["company_id", "branch_id", "source_upload_id", "business_date"],
        ["company_id", "branch_id", "id", "business_date"], ondelete="RESTRICT")
    op.create_foreign_key("fk_purchase_line_product_company", "purchase_lines", "products",
        ["company_id", "product_id"], ["company_id", "id"], ondelete="RESTRICT")

    op.create_table("stock_movement_reason_codes",
        sa.Column("code", sa.String(60), nullable=False),
        sa.Column("movement_type", sa.String(30), nullable=False),
        sa.Column("label", sa.String(120), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.CheckConstraint(
            "movement_type IN ('PURCHASE_RECEIPT','OTHER_INFLOW','POSITIVE_ADJUSTMENT','TRANSFER_IN',"
            "'WASTE','STAFF_CONSUMPTION','DAMAGE','NEGATIVE_ADJUSTMENT','OTHER_OUTFLOW','TRANSFER_OUT')",
            name="ck_stock_movement_reason_type"),
        sa.PrimaryKeyConstraint("code", "movement_type"),
    )
    op.bulk_insert(sa.table("stock_movement_reason_codes",
        sa.column("code", sa.String), sa.column("movement_type", sa.String),
        sa.column("label", sa.String), sa.column("is_active", sa.Boolean)),
        [{"code": code, "movement_type": movement_type, "label": label, "is_active": True}
         for code, movement_type, label in REASONS])

    op.create_table("purchase_receipt_identities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("branch_id", sa.Uuid(), nullable=False),
        sa.Column("receipt_event_id", sa.String(150), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id", "branch_id"], ["branches.company_id", "branches.id"],
            ondelete="RESTRICT", name="fk_purchase_receipt_identity_branch_scope"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "branch_id", "receipt_event_id", name="uq_purchase_receipt_event_scope"),
        sa.UniqueConstraint("company_id", "branch_id", "id", name="uq_purchase_receipt_identity_scope"),
    )
    op.create_index("ix_purchase_receipt_identities_company_id", "purchase_receipt_identities", ["company_id"])
    op.create_index("ix_purchase_receipt_identities_branch_id", "purchase_receipt_identities", ["branch_id"])
    op.create_foreign_key("fk_purchase_line_receipt_identity_scope", "purchase_lines",
        "purchase_receipt_identities", ["company_id", "branch_id", "receipt_identity_id"],
        ["company_id", "branch_id", "id"], ondelete="RESTRICT")

    op.create_table("purchase_receipt_current_lines",
        sa.Column("receipt_identity_id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("branch_id", sa.Uuid(), nullable=False),
        sa.Column("purchase_line_id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id", "branch_id", "receipt_identity_id"],
            ["purchase_receipt_identities.company_id", "purchase_receipt_identities.branch_id",
             "purchase_receipt_identities.id"], ondelete="CASCADE", name="fk_purchase_current_identity_scope"),
        sa.ForeignKeyConstraint(["receipt_identity_id", "purchase_line_id"],
            ["purchase_lines.receipt_identity_id", "purchase_lines.id"], ondelete="RESTRICT",
            name="fk_purchase_current_line_identity"),
        sa.PrimaryKeyConstraint("receipt_identity_id"),
        sa.UniqueConstraint("purchase_line_id", name="uq_purchase_receipt_current_line"),
    )
    op.create_index("ix_purchase_receipt_current_lines_branch_id", "purchase_receipt_current_lines", ["branch_id"])

    op.create_table("stock_transfers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("ingredient_product_id", sa.Uuid(), nullable=False),
        sa.Column("source_branch_id", sa.Uuid(), nullable=False),
        sa.Column("destination_branch_id", sa.Uuid(), nullable=False),
        sa.Column("movement_date", sa.Date(), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("unit", sa.String(30), nullable=False),
        sa.Column("source_batch_number", sa.String(120), nullable=True),
        sa.Column("destination_batch_number", sa.String(120), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_stock_transfer_quantity_positive"),
        sa.CheckConstraint("source_branch_id <> destination_branch_id", name="ck_stock_transfer_distinct_branches"),
        sa.ForeignKeyConstraint(["company_id", "source_branch_id"], ["branches.company_id", "branches.id"],
            ondelete="RESTRICT", name="fk_stock_transfer_source_branch"),
        sa.ForeignKeyConstraint(["company_id", "destination_branch_id"], ["branches.company_id", "branches.id"],
            ondelete="RESTRICT", name="fk_stock_transfer_destination_branch"),
        sa.ForeignKeyConstraint(["company_id", "ingredient_product_id", "unit"],
            ["products.company_id", "products.id", "products.unit_of_measure"],
            ondelete="RESTRICT", name="fk_stock_transfer_ingredient_unit"),
        sa.ForeignKeyConstraint(["company_id", "created_by_user_id"],
            ["company_memberships.company_id", "company_memberships.user_id"],
            ondelete="RESTRICT", name="fk_stock_transfer_creator_membership"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "company_id", "ingredient_product_id", "movement_date", "quantity", "unit",
            name="uq_stock_transfer_movement_ref"),
    )
    for name, cols in (("company_id", ["company_id"]), ("ingredient_product_id", ["ingredient_product_id"]),
                       ("source_branch_id", ["source_branch_id"]), ("destination_branch_id", ["destination_branch_id"]),
                       ("movement_date", ["movement_date"])):
        op.create_index(f"ix_stock_transfers_{name}", "stock_transfers", cols)

    op.create_table("stock_movements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("branch_id", sa.Uuid(), nullable=False),
        sa.Column("ingredient_product_id", sa.Uuid(), nullable=False),
        sa.Column("movement_date", sa.Date(), nullable=False),
        sa.Column("movement_type", sa.String(30), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("unit", sa.String(30), nullable=False),
        sa.Column("batch_number", sa.String(120), nullable=True),
        sa.Column("source_upload_id", sa.Uuid(), nullable=True),
        sa.Column("purchase_line_id", sa.Uuid(), nullable=True),
        sa.Column("transfer_id", sa.Uuid(), nullable=True),
        sa.Column("origin_type", sa.String(20), nullable=False),
        sa.Column("physical_event_id", sa.Uuid(), nullable=False),
        sa.Column("source_reference", sa.String(150), nullable=True),
        sa.Column("reason_code", sa.String(60), nullable=True),
        sa.Column("reason_detail", sa.String(500), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("voided_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("void_reason", sa.String(500), nullable=True),
        sa.CheckConstraint(
            "movement_type IN ('PURCHASE_RECEIPT','OTHER_INFLOW','POSITIVE_ADJUSTMENT','TRANSFER_IN',"
            "'WASTE','STAFF_CONSUMPTION','DAMAGE','NEGATIVE_ADJUSTMENT','OTHER_OUTFLOW','TRANSFER_OUT')",
            name="ck_stock_movement_type"),
        sa.CheckConstraint("quantity > 0", name="ck_stock_movement_quantity_positive"),
        sa.CheckConstraint("origin_type IN ('UPLOAD','MANUAL')", name="ck_stock_movement_origin_type"),
        sa.CheckConstraint("(origin_type='UPLOAD' AND source_upload_id IS NOT NULL) OR "
            "(origin_type='MANUAL' AND source_upload_id IS NULL AND created_by_user_id IS NOT NULL)",
            name="ck_stock_movement_origin_source"),
        sa.CheckConstraint("(movement_type='PURCHASE_RECEIPT' AND purchase_line_id IS NOT NULL AND source_upload_id IS NOT NULL) OR "
            "(movement_type<>'PURCHASE_RECEIPT' AND purchase_line_id IS NULL)", name="ck_stock_movement_purchase_link"),
        sa.CheckConstraint("(movement_type IN ('TRANSFER_IN','TRANSFER_OUT') AND transfer_id IS NOT NULL) OR "
            "(movement_type NOT IN ('TRANSFER_IN','TRANSFER_OUT') AND transfer_id IS NULL)", name="ck_stock_movement_transfer_link"),
        sa.CheckConstraint("movement_type NOT IN ('POSITIVE_ADJUSTMENT','NEGATIVE_ADJUSTMENT') OR reason_code IS NOT NULL",
            name="ck_stock_movement_adjustment_reason_required"),
        sa.CheckConstraint("origin_type <> 'MANUAL' OR reason_code IS NOT NULL",
            name="ck_stock_movement_manual_reason_required"),
        sa.CheckConstraint("(voided_at IS NULL AND voided_by_user_id IS NULL AND void_reason IS NULL) OR "
            "(voided_at IS NOT NULL AND voided_by_user_id IS NOT NULL AND length(trim(void_reason)) > 0)",
            name="ck_stock_movement_void_audit_complete"),
        sa.CheckConstraint("origin_type='MANUAL' OR voided_at IS NULL",
            name="ck_stock_movement_upload_not_voidable"),
        sa.ForeignKeyConstraint(["company_id", "branch_id"], ["branches.company_id", "branches.id"],
            ondelete="RESTRICT", name="fk_stock_movement_branch_scope"),
        sa.ForeignKeyConstraint(["company_id", "ingredient_product_id", "unit"],
            ["products.company_id", "products.id", "products.unit_of_measure"],
            ondelete="RESTRICT", name="fk_stock_movement_ingredient_unit"),
        sa.ForeignKeyConstraint(["company_id", "branch_id", "source_upload_id"],
            ["daily_uploads.company_id", "daily_uploads.branch_id", "daily_uploads.id"],
            ondelete="RESTRICT", name="fk_stock_movement_source_upload_scope"),
        sa.ForeignKeyConstraint(["company_id", "branch_id", "source_upload_id", "ingredient_product_id",
            "movement_date", "quantity", "unit", "purchase_line_id"],
            ["purchase_lines.company_id", "purchase_lines.branch_id", "purchase_lines.source_upload_id",
             "purchase_lines.product_id", "purchase_lines.receipt_date", "purchase_lines.quantity_received",
             "purchase_lines.purchase_unit", "purchase_lines.id"],
            ondelete="RESTRICT", name="fk_stock_movement_purchase_source"),
        sa.ForeignKeyConstraint(["transfer_id", "company_id", "ingredient_product_id", "movement_date", "quantity", "unit"],
            ["stock_transfers.id", "stock_transfers.company_id", "stock_transfers.ingredient_product_id",
             "stock_transfers.movement_date", "stock_transfers.quantity", "stock_transfers.unit"],
            ondelete="RESTRICT", name="fk_stock_movement_transfer_event"),
        sa.ForeignKeyConstraint(["reason_code", "movement_type"],
            ["stock_movement_reason_codes.code", "stock_movement_reason_codes.movement_type"],
            ondelete="RESTRICT", name="fk_stock_movement_reason_type"),
        sa.ForeignKeyConstraint(["company_id", "created_by_user_id"],
            ["company_memberships.company_id", "company_memberships.user_id"],
            ondelete="RESTRICT", name="fk_stock_movement_creator_membership"),
        sa.ForeignKeyConstraint(["company_id", "voided_by_user_id"],
            ["company_memberships.company_id", "company_memberships.user_id"],
            ondelete="RESTRICT", name="fk_stock_movement_void_actor_membership"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("purchase_line_id", name="uq_stock_movement_purchase_line"),
        sa.UniqueConstraint("transfer_id", "movement_type", name="uq_stock_movement_transfer_leg"),
    )
    for name, cols in (("company_id", ["company_id"]), ("branch_id", ["branch_id"]),
                       ("ingredient_product_id", ["ingredient_product_id"]),
                       ("movement_date", ["movement_date"]), ("source_upload_id", ["source_upload_id"]),
                       ("purchase_line_id", ["purchase_line_id"]), ("transfer_id", ["transfer_id"])):
        op.create_index(f"ix_stock_movements_{name}", "stock_movements", cols)
    op.create_index("ix_stock_movement_company_branch_date", "stock_movements",
        ["company_id", "branch_id", "movement_date"])
    op.create_index("ix_stock_movement_company_ingredient_date", "stock_movements",
        ["company_id", "ingredient_product_id", "movement_date"])
    op.create_index("uq_stock_movement_upload_event", "stock_movements",
        ["source_upload_id", "physical_event_id", "ingredient_product_id",
         sa.text("coalesce(batch_number, '')")], unique=True,
        postgresql_where=sa.text("source_upload_id IS NOT NULL"))
    op.create_index("uq_stock_movement_manual_event", "stock_movements",
        ["company_id", "branch_id", "physical_event_id", "ingredient_product_id",
         sa.text("coalesce(batch_number, '')")], unique=True,
        postgresql_where=sa.text("source_upload_id IS NULL"))

    op.create_table("stock_coverage_declarations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("branch_id", sa.Uuid(), nullable=False),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("source_upload_id", sa.Uuid(), nullable=False),
        sa.Column("ingredient_product_id", sa.Uuid(), nullable=False),
        sa.Column("unit", sa.String(30), nullable=False),
        sa.Column("coverage_dimension", sa.String(30), nullable=False),
        sa.Column("scope_type", sa.String(20), nullable=False),
        sa.Column("batch_number", sa.String(120), nullable=True),
        sa.Column("movement_type", sa.String(30), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("inventory_snapshot_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("coverage_dimension IN ('INGREDIENT','BATCH','OPENING_STOCK','CLOSING_STOCK','MOVEMENT_CATEGORY')",
            name="ck_stock_coverage_dimension"),
        sa.CheckConstraint("scope_type IN ('INGREDIENT','ALL_BATCHES','BATCH')", name="ck_stock_coverage_scope_type"),
        sa.CheckConstraint("status IN ('COMPLETE','PARTIAL','UNREPORTED','NOT_APPLICABLE','NO_STOCK')",
            name="ck_stock_coverage_status"),
        sa.CheckConstraint("(scope_type='BATCH' AND batch_number IS NOT NULL) OR "
            "(scope_type<>'BATCH' AND batch_number IS NULL)", name="ck_stock_coverage_batch_scope"),
        sa.CheckConstraint("(coverage_dimension='MOVEMENT_CATEGORY' AND movement_type IS NOT NULL) OR "
            "(coverage_dimension<>'MOVEMENT_CATEGORY' AND movement_type IS NULL)", name="ck_stock_coverage_movement_type"),
        sa.CheckConstraint("status<>'NO_STOCK' OR coverage_dimension IN ('INGREDIENT','BATCH','OPENING_STOCK','CLOSING_STOCK')",
            name="ck_stock_coverage_no_stock_dimension"),
        sa.CheckConstraint("coverage_dimension<>'INGREDIENT' OR scope_type='INGREDIENT'",
            name="ck_stock_coverage_ingredient_scope"),
        sa.CheckConstraint("coverage_dimension<>'BATCH' OR scope_type='ALL_BATCHES'",
            name="ck_stock_coverage_batch_dimension_scope"),
        sa.ForeignKeyConstraint(["company_id", "branch_id", "source_upload_id", "business_date"],
            ["daily_uploads.company_id", "daily_uploads.branch_id", "daily_uploads.id", "daily_uploads.business_date"],
            ondelete="RESTRICT", name="fk_stock_coverage_upload_scope"),
        sa.ForeignKeyConstraint(["company_id", "ingredient_product_id", "unit"],
            ["products.company_id", "products.id", "products.unit_of_measure"],
            ondelete="RESTRICT", name="fk_stock_coverage_ingredient_unit"),
        sa.ForeignKeyConstraint(["inventory_snapshot_id", "source_upload_id", "company_id", "branch_id",
            "business_date", "ingredient_product_id", "batch_number"],
            ["inventory_snapshots.id", "inventory_snapshots.source_upload_id", "inventory_snapshots.company_id",
             "inventory_snapshots.branch_id", "inventory_snapshots.business_date",
             "inventory_snapshots.product_id", "inventory_snapshots.batch_number"],
            ondelete="RESTRICT", name="fk_stock_coverage_inventory_snapshot"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("uq_stock_coverage_declaration_scope", "stock_coverage_declarations",
        ["source_upload_id", "ingredient_product_id", "coverage_dimension", "scope_type",
         sa.text("coalesce(batch_number, '')"), sa.text("coalesce(movement_type, '')")], unique=True)
    for name, cols in (("company_id", ["company_id"]), ("branch_id", ["branch_id"]),
                       ("source_upload_id", ["source_upload_id"]),
                       ("ingredient_product_id", ["ingredient_product_id"])):
        op.create_index(f"ix_stock_coverage_declarations_{name}", "stock_coverage_declarations", cols)
    op.create_index("ix_stock_coverage_company_branch_date", "stock_coverage_declarations",
        ["company_id", "branch_id", "business_date"])

    # PostgreSQL enforces cross-table ingredient and unit rules.
    op.execute("""
        CREATE FUNCTION tavuno_validate_stock_movement() RETURNS trigger AS $$
        DECLARE p_kind text; p_unit text; pl_unit text; pl_batch text;
        BEGIN
          SELECT product_kind, unit_of_measure INTO p_kind, p_unit
            FROM products WHERE id=NEW.ingredient_product_id AND company_id=NEW.company_id;
          IF p_kind IS DISTINCT FROM 'INGREDIENT' THEN
            RAISE EXCEPTION 'stock movement product must be an INGREDIENT in the same company';
          END IF;
          IF p_unit IS DISTINCT FROM NEW.unit THEN
            RAISE EXCEPTION 'stock movement unit must equal the ingredient canonical unit';
          END IF;
          IF NEW.purchase_line_id IS NOT NULL THEN
            SELECT purchase_unit, batch_number INTO pl_unit, pl_batch
              FROM purchase_lines WHERE id=NEW.purchase_line_id;
            IF pl_unit IS NULL OR pl_unit IS DISTINCT FROM NEW.unit OR pl_batch IS DISTINCT FROM NEW.batch_number THEN
              RAISE EXCEPTION 'purchase receipt movement requires a reliable matching purchase unit and batch';
            END IF;
          END IF;
          IF NEW.reason_code IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM stock_movement_reason_codes r
             WHERE r.code=NEW.reason_code AND r.movement_type=NEW.movement_type AND r.is_active
          ) THEN
            RAISE EXCEPTION 'stock movement reason is inactive or incompatible with movement type';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("CREATE TRIGGER trg_tavuno_validate_stock_movement BEFORE INSERT OR UPDATE ON stock_movements "
        "FOR EACH ROW EXECUTE FUNCTION tavuno_validate_stock_movement()")
    op.execute("""
        CREATE FUNCTION tavuno_validate_transfer_pair() RETURNS trigger AS $$
        DECLARE transfer_key uuid; transfer_row stock_transfers%ROWTYPE; leg_count integer;
                out_count integer; in_count integer; bad_count integer;
        BEGIN
          IF TG_TABLE_NAME = 'stock_transfers' THEN
            transfer_key := COALESCE(NEW.id, OLD.id);
          ELSE
            transfer_key := COALESCE(NEW.transfer_id, OLD.transfer_id);
          END IF;
          IF transfer_key IS NULL THEN RETURN NULL; END IF;
          SELECT * INTO transfer_row FROM stock_transfers WHERE id=transfer_key;
          IF NOT FOUND THEN
            IF EXISTS (SELECT 1 FROM stock_movements WHERE transfer_id=transfer_key) THEN
              RAISE EXCEPTION 'stock transfer movement has no transfer record';
            END IF;
            RETURN NULL;
          END IF;
          SELECT count(*), count(*) FILTER (WHERE movement_type='TRANSFER_OUT'),
                 count(*) FILTER (WHERE movement_type='TRANSFER_IN'),
                 count(*) FILTER (WHERE NOT (
                   (movement_type='TRANSFER_OUT' AND branch_id=transfer_row.source_branch_id
                     AND batch_number IS NOT DISTINCT FROM transfer_row.source_batch_number) OR
                   (movement_type='TRANSFER_IN' AND branch_id=transfer_row.destination_branch_id
                     AND batch_number IS NOT DISTINCT FROM transfer_row.destination_batch_number)
                 ) OR company_id<>transfer_row.company_id
                   OR ingredient_product_id<>transfer_row.ingredient_product_id
                   OR movement_date<>transfer_row.movement_date
                   OR quantity<>transfer_row.quantity OR unit<>transfer_row.unit)
            INTO leg_count, out_count, in_count, bad_count
            FROM stock_movements WHERE transfer_id=transfer_key;
          IF leg_count<>2 OR out_count<>1 OR in_count<>1 OR bad_count<>0 THEN
            RAISE EXCEPTION 'stock transfer must have exactly one matching inflow and outflow leg';
          END IF;
          RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("CREATE CONSTRAINT TRIGGER trg_tavuno_transfer_pair_movement "
        "AFTER INSERT OR UPDATE OR DELETE ON stock_movements DEFERRABLE INITIALLY DEFERRED "
        "FOR EACH ROW EXECUTE FUNCTION tavuno_validate_transfer_pair()")
    op.execute("CREATE CONSTRAINT TRIGGER trg_tavuno_transfer_pair_parent "
        "AFTER INSERT OR UPDATE OR DELETE ON stock_transfers DEFERRABLE INITIALLY DEFERRED "
        "FOR EACH ROW EXECUTE FUNCTION tavuno_validate_transfer_pair()")
    op.execute("""
        CREATE FUNCTION tavuno_guard_stock_product_change() RETURNS trigger AS $$
        BEGIN
          IF (NEW.product_kind IS DISTINCT FROM 'INGREDIENT' OR
              NEW.unit_of_measure IS DISTINCT FROM OLD.unit_of_measure)
             AND EXISTS (SELECT 1 FROM stock_movements m WHERE m.ingredient_product_id=OLD.id) THEN
            RAISE EXCEPTION 'ingredient kind or canonical unit cannot change while stock movements exist';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("CREATE TRIGGER trg_tavuno_guard_stock_product_change BEFORE UPDATE OF product_kind, unit_of_measure "
        "ON products FOR EACH ROW EXECUTE FUNCTION tavuno_guard_stock_product_change()")


def downgrade() -> None:
    # Do not discard ledger/identity/coverage data or fail after retained versions
    # make the old uniqueness rules impossible to restore.
    connection = op.get_bind()
    for table in ("stock_movements", "stock_transfers", "stock_coverage_declarations",
                  "purchase_receipt_current_lines", "purchase_receipt_identities"):
        if connection.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one():
            raise RuntimeError(f"Cannot downgrade: {table} contains data.")
    if connection.execute(sa.text("""
        SELECT EXISTS (SELECT 1 FROM inventory_snapshots
          GROUP BY company_id, branch_id, business_date, product_id, batch_number HAVING count(*) > 1)
    """)).scalar_one():
        raise RuntimeError("Cannot downgrade: retained inventory versions conflict with the prior unique key.")
    if connection.execute(sa.text("""
        SELECT EXISTS (SELECT 1 FROM purchase_lines
          GROUP BY company_id, branch_id, business_date, receipt_id, receipt_line_id HAVING count(*) > 1)
    """)).scalar_one():
        raise RuntimeError("Cannot downgrade: retained purchase versions conflict with the prior unique key.")

    op.execute("DROP TRIGGER trg_tavuno_guard_stock_product_change ON products")
    op.execute("DROP FUNCTION tavuno_guard_stock_product_change()")
    op.execute("DROP TRIGGER trg_tavuno_transfer_pair_parent ON stock_transfers")
    op.execute("DROP TRIGGER trg_tavuno_transfer_pair_movement ON stock_movements")
    op.execute("DROP FUNCTION tavuno_validate_transfer_pair()")
    op.execute("DROP TRIGGER trg_tavuno_validate_stock_movement ON stock_movements")
    op.execute("DROP FUNCTION tavuno_validate_stock_movement()")
    for name in ("ix_stock_coverage_company_branch_date", "ix_stock_coverage_declarations_ingredient_product_id",
                 "ix_stock_coverage_declarations_source_upload_id", "ix_stock_coverage_declarations_branch_id",
                 "ix_stock_coverage_declarations_company_id", "uq_stock_coverage_declaration_scope"):
        op.drop_index(name, table_name="stock_coverage_declarations")
    op.drop_table("stock_coverage_declarations")
    for name in ("ix_stock_movement_manual_event", "ix_stock_movement_upload_event",
                 "ix_stock_movement_company_ingredient_date", "ix_stock_movement_company_branch_date",
                 "ix_stock_movements_transfer_id", "ix_stock_movements_purchase_line_id",
                 "ix_stock_movements_source_upload_id", "ix_stock_movements_movement_date",
                 "ix_stock_movements_ingredient_product_id", "ix_stock_movements_branch_id",
                 "ix_stock_movements_company_id"):
        op.drop_index(name, table_name="stock_movements")
    op.drop_table("stock_movements")
    for name in ("ix_stock_transfers_movement_date", "ix_stock_transfers_destination_branch_id",
                 "ix_stock_transfers_source_branch_id", "ix_stock_transfers_ingredient_product_id",
                 "ix_stock_transfers_company_id"):
        op.drop_index(name, table_name="stock_transfers")
    op.drop_table("stock_transfers")
    op.drop_index("ix_purchase_receipt_current_lines_branch_id", table_name="purchase_receipt_current_lines")
    op.drop_table("purchase_receipt_current_lines")
    op.drop_index("ix_purchase_receipt_identities_branch_id", table_name="purchase_receipt_identities")
    op.drop_index("ix_purchase_receipt_identities_company_id", table_name="purchase_receipt_identities")
    op.drop_table("purchase_receipt_identities")
    op.drop_table("stock_movement_reason_codes")
    op.drop_constraint("fk_purchase_line_receipt_identity_scope", "purchase_lines", type_="foreignkey")
    op.drop_constraint("fk_purchase_line_product_company", "purchase_lines", type_="foreignkey")
    op.drop_constraint("fk_purchase_line_upload_scope", "purchase_lines", type_="foreignkey")
    op.drop_constraint("uq_purchase_movement_source_ref", "purchase_lines", type_="unique")
    op.drop_constraint("uq_purchase_identity_line_ref", "purchase_lines", type_="unique")
    op.drop_index("ix_purchase_lines_receipt_identity_id", table_name="purchase_lines")
    op.drop_column("purchase_lines", "receipt_identity_id")
    op.drop_constraint("uq_purchase_source_upload_line", "purchase_lines", type_="unique")
    op.create_unique_constraint("uq_purchase_source_line", "purchase_lines",
        ["company_id", "branch_id", "business_date", "receipt_id", "receipt_line_id"])
    op.drop_constraint("fk_inventory_snapshot_product_company", "inventory_snapshots", type_="foreignkey")
    op.drop_constraint("fk_inventory_snapshot_upload_scope", "inventory_snapshots", type_="foreignkey")
    op.drop_constraint("uq_inventory_snapshot_coverage_ref", "inventory_snapshots", type_="unique")
    op.drop_constraint("uq_inventory_snapshot_upload_batch", "inventory_snapshots", type_="unique")
    op.create_unique_constraint("uq_inventory_snapshot_batch", "inventory_snapshots",
        ["company_id", "branch_id", "business_date", "product_id", "batch_number"])
    op.drop_constraint("uq_daily_upload_company_branch_id_date", "daily_uploads", type_="unique")
    op.drop_constraint("uq_daily_upload_company_branch_id", "daily_uploads", type_="unique")
    op.drop_constraint("uq_product_company_id_unit", "products", type_="unique")
    op.drop_constraint("uq_product_company_id", "products", type_="unique")
    op.drop_constraint("uq_branch_company_id_id", "branches", type_="unique")
