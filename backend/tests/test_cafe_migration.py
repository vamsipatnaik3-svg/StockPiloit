from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory


def test_cafe_migration_follows_existing_head_and_renders_additive_sql():
    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)

    assert scripts.get_current_head() == "af010cafe006"
    workbook_revision = scripts.get_revision("3f011cafe002")
    assert workbook_revision.down_revision == "0b011cafe001"
    stock_revision = scripts.get_revision("4c010a9b7d21")
    assert stock_revision.down_revision == "3f011cafe002"
    receipt_revision = scripts.get_revision("7e010cafe003")
    assert receipt_revision.down_revision == "4c010a9b7d21"
    sales_retention_revision = scripts.get_revision("8e010cafe004")
    assert sales_retention_revision.down_revision == "7e010cafe003"
    grant_revision = scripts.get_revision("9f010cafe005")
    assert grant_revision.down_revision == "8e010cafe004"
    staff_revision = scripts.get_revision("af010cafe006")
    assert staff_revision.down_revision == "9f010cafe005"
    revision = scripts.get_revision("0b011cafe001")
    assert revision.down_revision == "6c010a4fb32e"

    output = StringIO()
    with redirect_stdout(output):
        command.upgrade(config, "head", sql=True)
    sql = output.getvalue()

    assert "ALTER TABLE products ADD COLUMN product_kind VARCHAR(20) DEFAULT 'LEGACY' NOT NULL" in sql
    assert "CREATE TABLE recipe_versions" in sql
    assert "CREATE TABLE modifier_recipe_ingredients" in sql
    assert "CREATE TABLE sales_record_modifiers" in sql
    assert "ALTER TABLE sales_records ADD COLUMN recipe_version_id UUID" in sql
    assert "ALTER TABLE sales_records ADD COLUMN sales_channel VARCHAR(40)" in sql
    assert "ALTER TABLE sales_record_modifiers ADD COLUMN selection_quantity NUMERIC(18, 4)" in sql
    assert "ALTER TABLE inventory_snapshots ADD COLUMN staff_consumption_quantity NUMERIC(18, 4)" in sql
    assert "ALTER TABLE purchase_lines ADD COLUMN purchase_unit VARCHAR(30)" in sql
    assert "DROP CONSTRAINT uq_inventory_snapshot_batch" in sql
    assert "DROP CONSTRAINT uq_purchase_source_line" in sql
    assert "uq_inventory_snapshot_upload_batch" in sql
    assert "uq_purchase_source_upload_line" in sql
    assert "CREATE TABLE stock_movements" in sql
    assert "CREATE TABLE stock_transfers" in sql
    assert "CREATE TABLE stock_coverage_declarations" in sql
    assert "CREATE TABLE purchase_receipt_identities" in sql
    assert "CREATE TABLE purchase_receipt_current_lines" in sql
    assert "fk_stock_movement_source_upload_scope" in sql
    assert "fk_stock_movement_ingredient_unit" in sql
    assert "CREATE CONSTRAINT TRIGGER trg_tavuno_transfer_pair_movement" in sql
    assert "CREATE CONSTRAINT TRIGGER trg_tavuno_transfer_pair_parent" in sql
    assert "DEFERRABLE INITIALLY DEFERRED" in sql
    assert "DROP CONSTRAINT uq_purchase_source_upload_line" in sql
    assert "CREATE UNIQUE INDEX uq_purchase_legacy_source_line" in sql
    assert "CREATE UNIQUE INDEX uq_purchase_source_receipt_event" in sql
    assert "DROP CONSTRAINT uq_sales_business_source" in sql
    assert "uq_sales_upload_source" in sql
    assert "CREATE TABLE analyst_analytics_grants" in sql
    assert "CREATE TABLE analyst_analytics_grant_branches" in sql
    assert "uq_analyst_grant_one_active" in sql
    assert "fk_analyst_grant_target_membership" in sql
    assert "fk_analyst_grant_branch_company_scope" in sql
    assert "CREATE TABLE stock_count_submissions" in sql
    assert "CREATE TABLE stock_count_lines" in sql
    assert "CREATE TABLE purchase_receipt_confirmations" in sql
    assert "ALTER TABLE stock_movements ADD COLUMN occurred_at TIMESTAMP WITH TIME ZONE" in sql
    assert "fk_stock_count_line_ingredient_unit" in sql
    assert "fk_receipt_confirmation_ingredient_unit" in sql
