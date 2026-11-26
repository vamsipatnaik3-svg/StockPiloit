from datetime import date, datetime
from io import BytesIO
from uuid import UUID, uuid4

from openpyxl import Workbook
from decimal import Decimal
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password
from app.models import (BranchMembership, CompanyMembership, DailyUpload,
    HistoricalImportItem, HistoricalImportJob, InventorySnapshot, PurchaseLine,
    SalesRecord, SalesRecordModifier, User, PurchaseReceiptIdentity,
    PurchaseReceiptCurrentLine, StockMovement, StockCoverageDeclaration)
import app.services.upload_processing as upload_processing


def workbook(net_amount=118, metadata_date="2026-11-25", tax_amount=18, business_date="2026-11-25", branch_reference="BR-001"):
    wb = Workbook()
    meta = wb.active
    meta.title = "Metadata"
    for row in [("Field", "Value"), ("Template Version", "1.0"), ("Business Date", metadata_date),
                ("Branch Reference", branch_reference), ("Currency", "INR"), ("Source Granularity", "TRANSACTION")]:
        meta.append(row)
    sales = wb.create_sheet("Daily Sales")
    sales.append(["Transaction ID", "Line ID", "Transaction DateTime", "SKU", "Quantity", "Unit Selling Price", "Discount Amount", "Tax Amount", "Net Amount"])
    sales.append(["BILL-1", "1", f"{business_date} 10:00", "SKU-001", 1, 100, 0, tax_amount, net_amount])
    inventory = wb.create_sheet("Inventory")
    inventory.append(["SKU", "Batch Number", "Opening Quantity", "Closing Quantity", "Unit", "Expiry Date", "Unit Cost", "Damaged Quantity", "Wasted Quantity", "Adjustment Quantity", "Adjustment Reason"])
    inventory.append(["SKU-001", "LOT-A", 8, 9, "EA", None, 50, 0, 0, 0, None])
    purchases = wb.create_sheet("Purchases")
    purchases.append(["Receipt ID", "Receipt Line ID", "Receipt Date", "Supplier Name", "SKU", "Quantity Received", "Unit Purchase Price", "Batch Number", "Expiry Date"])
    purchases.append(["GRN-1", "1", business_date, "Supplier", "SKU-001", 2, 50, "LOT-A", None])
    output = BytesIO()
    wb.save(output)
    return output.getvalue()


def aggregated_workbook(business_date="2026-11-25"):
    wb = Workbook()
    metadata = wb.active
    metadata.title = "Metadata"
    for row in [("Field", "Value"), ("Template Version", "1.0"), ("Business Date", business_date),
                ("Branch Reference", "BR-001"), ("Currency", "INR"), ("Source Granularity", "AGGREGATED")]:
        metadata.append(row)
    sales = wb.create_sheet("Daily Sales")
    sales.append(["Transaction ID", "Line ID", "Transaction DateTime", "SKU", "Quantity", "Unit Selling Price", "Discount Amount", "Tax Amount", "Net Amount", "Source Reference", "Aggregate ID"])
    sales.append([None, None, None, "SKU-001", 3, 20, 0, 6, 66, "POS day total", f"POS-{business_date}"])
    wb.create_sheet("Inventory").append(["SKU", "Opening Quantity", "Closing Quantity", "Unit"])
    wb.create_sheet("Purchases").append(["Receipt ID", "Receipt Line ID", "Receipt Date", "SKU", "Quantity Received"])
    output = BytesIO()
    wb.save(output)
    return output.getvalue()


def cafe_workbook(branch_reference="BR-001", option="Oat milk", version="2.0", sales_sku="MENU-001", stock_sku="ING-001", purchase_sku="ING-001", purchase_unit="ml", sales_channel="DINE_IN"):
    wb = Workbook()
    metadata = wb.active
    metadata.title = "Metadata"
    for row in [("Field", "Value"), ("Template Version", version), ("Business Date", "2026-11-25"),
                ("Branch Reference", branch_reference), ("Currency", "INR"), ("Source Granularity", "AGGREGATED")]:
        metadata.append(row)
    sales = wb.create_sheet("Daily Sales")
    sales.append(["Transaction ID", "Line ID", "Transaction DateTime", "SKU", "Quantity", "Unit Selling Price", "Discount Amount", "Tax Amount", "Net Amount", "Source Reference", "Aggregate ID", "Sales Row Reference", "Sales Channel"])
    sales.append([None, None, None, sales_sku, 2, 100, 0, 0, 200, "POS close", "DAY-001", "SALE-ROW-A", sales_channel])
    modifiers = wb.create_sheet("Sales Modifiers")
    modifiers.append(["Sales Row Reference", "Modifier Group", "Modifier Option", "Selection Quantity"])
    modifiers.append(["SALE-ROW-A", "Milk choice", option, 1])
    modifiers.append(["SALE-ROW-A", "Milk choice", "Whole milk", 1])
    inventory = wb.create_sheet("Inventory")
    inventory.append(["SKU", "Batch Number", "Opening Quantity", "Closing Quantity", "Unit", "Expiry Date", "Unit Cost", "Damaged Quantity", "Wasted Quantity", "Adjustment Quantity", "Adjustment Reason", "Staff Consumption Quantity"])
    inventory.append([stock_sku, "BATCH-1", 1000, 1000, "ml", None, 0.1, 0, 0, 0, None, 10])
    purchases = wb.create_sheet("Purchases")
    purchases.append(["Receipt ID", "Receipt Line ID", "Receipt Date", "Supplier Name", "SKU", "Quantity Received", "Unit Purchase Price", "Batch Number", "Expiry Date", "Purchase Unit"])
    purchases.append(["GRN-1", "1", "2026-11-25", "Cafe supplier", purchase_sku, 100, 10, "BATCH-2", None, purchase_unit])
    output = BytesIO()
    wb.save(output)
    return output.getvalue()


def cafe_inventory_only_workbook(quantity_overrides=None):
    values = {
        "Opening Quantity": 100,
        "Closing Quantity": 100,
        "Damaged Quantity": 0,
        "Wasted Quantity": 0,
        "Adjustment Quantity": 0,
        "Staff Consumption Quantity": 0,
    }
    values.update(quantity_overrides or {})
    wb = Workbook()
    metadata = wb.active
    metadata.title = "Metadata"
    for row in [("Field", "Value"), ("Template Version", "2.0"), ("Business Date", "2026-11-25"),
                ("Branch Reference", "BR-001"), ("Currency", "INR"), ("Source Granularity", "AGGREGATED")]:
        metadata.append(row)
    sales = wb.create_sheet("Daily Sales")
    sales.append(["Transaction ID", "Line ID", "Transaction DateTime", "SKU", "Quantity", "Unit Selling Price", "Discount Amount", "Tax Amount", "Net Amount", "Source Reference", "Aggregate ID", "Sales Row Reference", "Sales Channel"])
    wb.create_sheet("Sales Modifiers").append(["Sales Row Reference", "Modifier Group", "Modifier Option", "Selection Quantity"])
    inventory = wb.create_sheet("Inventory")
    inventory.append(["SKU", "Batch Number", "Opening Quantity", "Closing Quantity", "Unit", "Expiry Date", "Unit Cost", "Damaged Quantity", "Wasted Quantity", "Adjustment Quantity", "Adjustment Reason", "Staff Consumption Quantity"])
    inventory.append(["ING-001", "BATCH-1", values["Opening Quantity"], values["Closing Quantity"], "ml", None, 0.1, values["Damaged Quantity"], values["Wasted Quantity"], values["Adjustment Quantity"], None, values["Staff Consumption Quantity"]])
    purchases = wb.create_sheet("Purchases")
    purchases.append(["Receipt ID", "Receipt Line ID", "Receipt Date", "Supplier Name", "SKU", "Quantity Received", "Unit Purchase Price", "Batch Number", "Expiry Date", "Purchase Unit"])
    output = BytesIO()
    wb.save(output)
    return output.getvalue()


def create_inventory_upload_context(client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "upload_storage_dir", str(tmp_path))
    token = register_owner(client)
    branch_id = client.post("/api/v1/branches", cookies={"stockpilot_session": token}, json={
        "name": "Main", "code": "BR-001", "country_code": "IN", "timezone": "Asia/Kolkata",
    }).json()["id"]
    product = client.post("/api/v1/products", cookies={"stockpilot_session": token}, json={
        "sku": "ING-001", "product_name": "Milk", "unit_of_measure": "ml", "product_kind": "INGREDIENT",
    })
    assert product.status_code == 201
    return token, branch_id


def register_owner(client):
    client.post("/api/v1/auth/register", json={
        "full_name": "Upload Owner", "email": "upload-owner@example.com",
        "password": "StockPilot_Test_123!", "company_name": "Upload Company",
        "industry": "grocery", "country_code": "IN", "currency": "INR", "timezone": "Asia/Kolkata",
    })
    response = client.post("/api/v1/auth/login", json={"email": "upload-owner@example.com", "password": "StockPilot_Test_123!"})
    return response.cookies.get("stockpilot_session")


def create_upload(client, token, branch_id, content, business_date="2026-11-25"):
    return client.post("/api/v1/uploads", data={"branch_id": branch_id, "business_date": business_date},
        files={"file": (f"daily-{business_date}.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        cookies={"stockpilot_session": token})


def process(client, token, upload_id):
    return client.post(f"/api/v1/uploads/{upload_id}/process", cookies={"stockpilot_session": token})


def assert_counts(db, sales, inventory, purchases):
    assert db.scalar(select(func.count()).select_from(SalesRecord)) == sales
    assert db.scalar(select(func.count()).select_from(InventorySnapshot)) == inventory
    assert db.scalar(select(func.count()).select_from(PurchaseLine)) == purchases


def test_versions_idempotency_and_date_isolation(test_environment, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "upload_storage_dir", str(tmp_path))
    client, sessions = test_environment
    token = register_owner(client)
    branch_response = client.post("/api/v1/branches", cookies={"stockpilot_session": token}, json={
        "name": "Main", "code": "BR-001", "country_code": "IN", "timezone": "Asia/Kolkata",
    })
    branch_id = branch_response.json()["id"]
    product_response = client.post("/api/v1/products", cookies={"stockpilot_session": token}, json={
        "sku": "SKU-001", "product_name": "Tea", "unit_of_measure": "EA",
    })
    assert product_response.status_code == 201

    # Scenario A: first valid upload becomes version 1 and current.
    first = create_upload(client, token, branch_id, workbook(metadata_date="25/11/2026"))
    assert first.status_code == 201 and first.json()["version"] == 1
    completed_first = process(client, token, first.json()["id"])
    assert completed_first.json()["processing_status"] == "COMPLETED"
    assert completed_first.json()["is_current"] is True
    with sessions() as db:
        assert_counts(db, 1, 1, 1)
        first_record = db.scalar(select(SalesRecord))
        assert first_record.source_upload_id.hex == first.json()["id"].replace("-", "")
        assert first_record.recipe_version_id is None
        assert db.scalar(select(InventorySnapshot)).source_upload_id == first_record.source_upload_id
        assert db.scalar(select(PurchaseLine)).source_upload_id == first_record.source_upload_id
        assert type(db.scalar(select(DailyUpload.business_date))) is date

    # Reprocessing the same current upload is idempotent and does not rewrite rows.
    replay = process(client, token, first.json()["id"])
    assert replay.json()["processing_status"] == "COMPLETED"
    with sessions() as db:
        assert_counts(db, 1, 1, 1)

    # Scenario B: a successful correction becomes version 2 while version 1 remains in history.
    second = create_upload(client, token, branch_id, workbook(net_amount=119, tax_amount=19))
    assert second.status_code == 201 and second.json()["version"] == 2
    completed_second = process(client, token, second.json()["id"])
    assert completed_second.json()["processing_status"] == "COMPLETED"
    assert completed_second.json()["is_current"] is True
    with sessions() as db:
        uploads = db.scalars(select(DailyUpload).order_by(DailyUpload.version)).all()
        assert [(item.version, item.is_current) for item in uploads] == [(1, False), (2, True)]
        assert_counts(db, 2, 2, 2)
        historical_sale = db.scalar(select(SalesRecord).where(
            SalesRecord.source_upload_id == UUID(first.json()["id"])))
        assert historical_sale is not None and historical_sale.net_amount == 118
        current_sale = db.scalar(select(SalesRecord).where(
            SalesRecord.source_upload_id == UUID(completed_second.json()["id"])))
        assert current_sale.source_upload_id.hex == second.json()["id"].replace("-", "")
        assert current_sale.net_amount == 119
        assert {item.source_upload_id.hex for item in db.scalars(select(InventorySnapshot)).all()} == {
            first.json()["id"].replace("-", ""), second.json()["id"].replace("-", "")}
        assert {item.source_upload_id.hex for item in db.scalars(select(PurchaseLine)).all()} == {
            first.json()["id"].replace("-", ""), second.json()["id"].replace("-", "")}

    # Retained source versions do not leak into current operational totals.
    inventory_view = client.get("/api/v1/analytics/inventory/overview?as_of_date=2026-11-25",
        cookies={"stockpilot_session": token})
    purchase_view = client.get("/api/v1/analytics/purchases/overview?start_date=2026-11-25&end_date=2026-11-25",
        cookies={"stockpilot_session": token})
    assert inventory_view.status_code == purchase_view.status_code == 200
    assert len(inventory_view.json()["products"]) == 1
    assert purchase_view.json()["total_lines"] == 1
    sales_view = client.get("/api/v1/analytics/overview?start_date=2026-11-25&end_date=2026-11-25",
        cookies={"stockpilot_session": token})
    assert sales_view.status_code == 200
    assert sales_view.json()["revenue"]["current"] == "119.0000"
    assert sales_view.json()["coverage"]["sales_lines"] == 1

    # A stale older version cannot be replayed to replace a newer successful correction.
    stale_replay = process(client, token, first.json()["id"])
    assert stale_replay.json()["processing_status"] == "SKIPPED"
    with sessions() as db:
        assert_counts(db, 2, 2, 2)
        assert db.scalar(select(DailyUpload).where(DailyUpload.is_current.is_(True))).version == 2

    # Scenario C: failed correction remains non-current; version 2 stays current.
    third = create_upload(client, token, branch_id, workbook(net_amount=118, tax_amount=17))
    assert third.status_code == 201 and third.json()["version"] == 3
    failed = process(client, token, third.json()["id"])
    assert failed.json()["processing_status"] == "VALIDATION_FAILED"
    assert failed.json()["is_current"] is False
    report = client.get(f"/api/v1/uploads/{third.json()['id']}/validation-report", cookies={"stockpilot_session": token}).json()
    assert any(issue["code"] == "NET_AMOUNT_MISMATCH" for issue in report["issues"])
    with sessions() as db:
        assert db.scalar(select(DailyUpload).where(DailyUpload.is_current.is_(True))).version == 2
        assert_counts(db, 2, 2, 2)

    # Scenario D: an independent date starts at version 1 and remains a separate current dataset.
    fourth = create_upload(client, token, branch_id,
        workbook(metadata_date="2026-11-26", business_date="2026-11-26"), business_date="2026-11-26")
    assert fourth.status_code == 201 and fourth.json()["version"] == 1
    assert process(client, token, fourth.json()["id"]).json()["is_current"] is True
    with sessions() as db:
        assert_counts(db, 3, 3, 3)
        currents = db.scalars(select(DailyUpload).where(DailyUpload.is_current.is_(True))).all()
        assert {item.business_date for item in currents} == {date(2026, 11, 25), date(2026, 11, 26)}


def test_equivalent_dates_pass_and_different_workbook_date_fails(test_environment, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "upload_storage_dir", str(tmp_path))
    client, _ = test_environment
    token = register_owner(client)
    branch_id = client.post("/api/v1/branches", cookies={"stockpilot_session": token}, json={
        "name": "Main", "code": "BR-001", "country_code": "IN", "timezone": "Asia/Kolkata",
    }).json()["id"]
    client.post("/api/v1/products", cookies={"stockpilot_session": token}, json={
        "sku": "SKU-001", "product_name": "Tea", "unit_of_measure": "EA",
    })

    for metadata_date in ("25/11/2026", "2026-11-25", datetime(2026, 11, 25), date(2026, 11, 25)):
        uploaded = create_upload(client, token, branch_id, workbook(metadata_date=metadata_date))
        result = process(client, token, uploaded.json()["id"])
        report = client.get(f"/api/v1/uploads/{uploaded.json()['id']}/validation-report", cookies={"stockpilot_session": token}).json()
        assert result.json()["processing_status"] == "COMPLETED"
        assert not any(issue["code"] == "BUSINESS_DATE_MISMATCH" for issue in report["issues"])

    different = create_upload(client, token, branch_id, workbook(metadata_date="2026-11-24"))
    result = process(client, token, different.json()["id"])
    report = client.get(f"/api/v1/uploads/{different.json()['id']}/validation-report", cookies={"stockpilot_session": token}).json()
    assert result.json()["processing_status"] == "VALIDATION_FAILED"
    assert any(issue["code"] == "BUSINESS_DATE_MISMATCH" for issue in report["issues"])


@pytest.mark.parametrize("quantity_field", [
    "Opening Quantity",
    "Closing Quantity",
    "Damaged Quantity",
    "Wasted Quantity",
    "Staff Consumption Quantity",
])
def test_negative_inventory_quantities_are_rejected(test_environment, tmp_path, monkeypatch, quantity_field):
    client, _ = test_environment
    token, branch_id = create_inventory_upload_context(client, tmp_path, monkeypatch)
    uploaded = create_upload(client, token, branch_id,
        cafe_inventory_only_workbook({quantity_field: Decimal("-1")}))

    result = process(client, token, uploaded.json()["id"])
    report = client.get(f"/api/v1/uploads/{uploaded.json()['id']}/validation-report",
        cookies={"stockpilot_session": token}).json()

    assert result.json()["processing_status"] == "VALIDATION_FAILED"
    assert any(issue["code"] == "NEGATIVE_INVENTORY" and quantity_field in issue["message"]
        for issue in report["issues"])


@pytest.mark.parametrize("adjustment", [Decimal("-5"), Decimal("5")])
def test_adjustment_quantity_is_a_signed_stock_movement(test_environment, tmp_path, monkeypatch, adjustment):
    client, _ = test_environment
    token, branch_id = create_inventory_upload_context(client, tmp_path, monkeypatch)
    uploaded = create_upload(client, token, branch_id,
        cafe_inventory_only_workbook({"Adjustment Quantity": adjustment}))

    result = process(client, token, uploaded.json()["id"])
    report = client.get(f"/api/v1/uploads/{uploaded.json()['id']}/validation-report",
        cookies={"stockpilot_session": token}).json()

    assert result.json()["processing_status"] == "COMPLETED"
    assert not any(issue["code"] == "NEGATIVE_INVENTORY" for issue in report["issues"])


def test_historical_import_skips_already_processed_and_repeated_upload(test_environment, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "upload_storage_dir", str(tmp_path))
    client, sessions = test_environment
    import app.api.routes.historical_imports as historical_imports
    monkeypatch.setattr(historical_imports, "SessionLocal", sessions)
    token = register_owner(client)
    branch_id = client.post("/api/v1/branches", cookies={"stockpilot_session": token}, json={
        "name": "Main", "code": "BR-001", "country_code": "IN", "timezone": "Asia/Kolkata",
    }).json()["id"]
    client.post("/api/v1/products", cookies={"stockpilot_session": token}, json={
        "sku": "SKU-001", "product_name": "Tea", "unit_of_measure": "EA",
    })
    upload = create_upload(client, token, branch_id, workbook())
    process(client, token, upload.json()["id"])

    first_job = client.post("/api/v1/historical-imports", cookies={"stockpilot_session": token}, json={"upload_ids": [upload.json()["id"]]})
    assert first_job.status_code == 202
    assert first_job.json()["status"] == "COMPLETED"
    assert first_job.json()["completed_files"] == 0
    assert first_job.json()["skipped_files"] == 1
    assert first_job.json()["progress_percent"] == 100
    detail = client.get(f"/api/v1/historical-imports/{first_job.json()['id']}", cookies={"stockpilot_session": token}).json()
    assert detail["files"][0]["status"] == "SKIPPED"

    repeated = client.post("/api/v1/historical-imports", cookies={"stockpilot_session": token}, json={"upload_ids": [upload.json()["id"]]})
    assert repeated.status_code == 202
    assert repeated.json()["skipped_files"] == 1
    with sessions() as db:
        assert_counts(db, 1, 1, 1)
        assert db.scalar(select(func.count()).select_from(HistoricalImportJob)) == 2
        assert db.scalar(select(func.count()).select_from(HistoricalImportItem).where(HistoricalImportItem.status == "SKIPPED")) == 2


def test_aggregate_sales_reprocessing_preserves_granularity_and_does_not_duplicate(test_environment, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "upload_storage_dir", str(tmp_path))
    client, sessions = test_environment
    token = register_owner(client)
    branch_id = client.post("/api/v1/branches", cookies={"stockpilot_session": token}, json={
        "name": "Main", "code": "BR-001", "country_code": "IN", "timezone": "Asia/Kolkata",
    }).json()["id"]
    client.post("/api/v1/products", cookies={"stockpilot_session": token}, json={
        "sku": "SKU-001", "product_name": "Tea", "unit_of_measure": "EA",
    })
    upload = create_upload(client, token, branch_id, aggregated_workbook())
    assert upload.status_code == 201
    assert process(client, token, upload.json()["id"]).json()["processing_status"] == "COMPLETED"
    assert process(client, token, upload.json()["id"]).json()["processing_status"] == "COMPLETED"
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(SalesRecord)) == 1
        record = db.scalar(select(SalesRecord))
        assert record.granularity == "AGGREGATED"
        assert record.aggregate_id == "POS-2026-11-25"
        assert record.transaction_id is None and record.line_id is None


def test_cafe_v2_processing_modifiers_classification_and_failed_correction(test_environment, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "upload_storage_dir", str(tmp_path))
    client, sessions = test_environment
    token = register_owner(client)
    branch_id = client.post("/api/v1/branches", cookies={"stockpilot_session": token}, json={
        "name": "Main", "code": "BR-001", "country_code": "IN", "timezone": "Asia/Kolkata",
    }).json()["id"]
    menu = client.post("/api/v1/products", cookies={"stockpilot_session": token}, json={
        "sku": "MENU-001", "product_name": "Cappuccino", "unit_of_measure": "pcs", "product_kind": "MENU_ITEM",
    }).json()
    ingredient = client.post("/api/v1/products", cookies={"stockpilot_session": token}, json={
        "sku": "ING-001", "product_name": "Milk", "unit_of_measure": "ml", "product_kind": "INGREDIENT",
    }).json()
    beans = client.post("/api/v1/products", cookies={"stockpilot_session": token}, json={
        "sku": "BEAN-001", "product_name": "Coffee beans", "unit_of_measure": "g", "product_kind": "INGREDIENT",
    }).json()
    group = client.post(f"/api/v1/recipes/menu-items/{menu['id']}/modifier-groups", cookies={"stockpilot_session": token}, json={
        "name": "Milk choice", "selection_min": 1, "selection_max": 1, "options": ["Oat milk", "Whole milk"],
    }).json()
    options = {option["name"]: option["id"] for option in group["options"]}
    version = client.post(f"/api/v1/recipes/menu-items/{menu['id']}/versions", cookies={"stockpilot_session": token}, json={
        "effective_from": "2026-01-01",
        "ingredients": [{"ingredient_product_id": beans["id"], "quantity": 18, "unit": "g"}],
        "modifier_ingredients": [
            {"modifier_option_id": options["Oat milk"], "ingredient_product_id": ingredient["id"], "quantity": 120, "unit": "ml"},
            {"modifier_option_id": options["Whole milk"], "ingredient_product_id": ingredient["id"], "quantity": 150, "unit": "ml"},
        ],
    })
    assert version.status_code == 201, version.text

    cafe_content = cafe_workbook()
    uploaded = create_upload(client, token, branch_id, cafe_content)
    completed = process(client, token, uploaded.json()["id"])
    assert completed.json()["processing_status"] == "COMPLETED"
    with sessions() as db:
        sale = db.scalar(select(SalesRecord))
        assert sale.product_id.hex == menu["id"].replace("-", "")
        assert sale.recipe_version_id.hex == version.json()["id"].replace("-", "")
        assert sale.sales_channel == "DINE_IN"
        selections = db.scalars(select(SalesRecordModifier).where(SalesRecordModifier.sales_record_id == sale.id)).all()
        assert {(item.modifier_option_id.hex, item.selection_quantity) for item in selections} == {
            (options["Oat milk"].replace("-", ""), Decimal("1.0000")),
            (options["Whole milk"].replace("-", ""), Decimal("1.0000")),
        }
        snapshot = db.scalar(select(InventorySnapshot))
        assert snapshot.product_id.hex == ingredient["id"].replace("-", "")
        assert snapshot.staff_consumption_quantity == Decimal("10.0000")
        purchase = db.scalar(select(PurchaseLine))
        assert purchase.purchase_unit == "ml"

    # A repeated successful processing is idempotent and adds no duplicate rows.
    assert process(client, token, uploaded.json()["id"]).json()["processing_status"] == "COMPLETED"
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(SalesRecord)) == 1
        assert db.scalar(select(func.count()).select_from(SalesRecordModifier)) == 2

    # Same uploaded bytes are deduplicated by upload storage and keep the existing row set.
    duplicate = create_upload(client, token, branch_id, cafe_content)
    assert duplicate.status_code == 409

    bad_classification = create_upload(client, token, branch_id, cafe_workbook(
        branch_reference="BR-001", sales_sku="ING-001"))
    failed = process(client, token, bad_classification.json()["id"])
    report = client.get(f"/api/v1/uploads/{bad_classification.json()['id']}/validation-report", cookies={"stockpilot_session": token}).json()
    assert failed.json()["processing_status"] == "VALIDATION_FAILED"
    assert any(issue["code"] == "INCORRECT_PRODUCT_KIND" for issue in report["issues"])
    with sessions() as db:
        assert db.scalar(select(DailyUpload).where(DailyUpload.is_current.is_(True))).id.hex == uploaded.json()["id"].replace("-", "")
        assert db.scalar(select(func.count()).select_from(SalesRecord)) == 1

    bad_ingredients = create_upload(client, token, branch_id, cafe_workbook(
        stock_sku="MENU-001", purchase_sku="MENU-001", purchase_unit="kg"))
    bad_ingredients_result = process(client, token, bad_ingredients.json()["id"])
    bad_ingredients_report = client.get(f"/api/v1/uploads/{bad_ingredients.json()['id']}/validation-report", cookies={"stockpilot_session": token}).json()
    assert bad_ingredients_result.json()["processing_status"] == "VALIDATION_FAILED"
    assert {(issue["sheet"], issue["code"]) for issue in bad_ingredients_report["issues"]} >= {
        ("Inventory", "INCORRECT_PRODUCT_KIND"), ("Purchases", "INCORRECT_PRODUCT_KIND"), ("Purchases", "UNIT_MISMATCH"),
    }

    bad_modifier = create_upload(client, token, branch_id, cafe_workbook(
        option="Not a real option"))
    failed_modifier = process(client, token, bad_modifier.json()["id"])
    modifier_report = client.get(f"/api/v1/uploads/{bad_modifier.json()['id']}/validation-report", cookies={"stockpilot_session": token}).json()
    assert failed_modifier.json()["processing_status"] == "VALIDATION_FAILED"
    assert any(issue["code"] == "UNKNOWN_MODIFIER_OPTION" for issue in modifier_report["issues"])
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(SalesRecord)) == 1
        assert db.scalar(select(func.count()).select_from(SalesRecordModifier)) == 2

    corrected = create_upload(client, token, branch_id, cafe_workbook(sales_channel="TAKEAWAY"))
    assert process(client, token, corrected.json()["id"]).json()["processing_status"] == "COMPLETED"
    with sessions() as db:
        assert db.scalar(select(DailyUpload).where(DailyUpload.is_current.is_(True))).id.hex == corrected.json()["id"].replace("-", "")
        assert db.scalar(select(func.count()).select_from(SalesRecord)) == 2
        assert db.scalar(select(func.count()).select_from(SalesRecordModifier)) == 4
        old_sale = db.scalar(select(SalesRecord).where(
            SalesRecord.source_upload_id == UUID(uploaded.json()["id"])))
        current_sale = db.scalar(select(SalesRecord).where(
            SalesRecord.source_upload_id == UUID(corrected.json()["id"])))
        assert old_sale is not None and old_sale.sales_channel == "DINE_IN"
        assert current_sale is not None and current_sale.sales_channel == "TAKEAWAY"
        assert db.scalar(select(func.count()).select_from(SalesRecordModifier).where(
            SalesRecordModifier.sales_record_id == old_sale.id)) == 2

    # Current sales APIs and theoretical consumption must exclude the retained
    # original version even though the same source identity occurs twice.
    product_metrics = client.get(
        "/api/v1/analytics/products/performance?start_date=2026-11-25&end_date=2026-11-25",
        cookies={"stockpilot_session": token})
    assert product_metrics.status_code == 200, product_metrics.text
    assert product_metrics.json()["top_products"][0]["quantity"] == "2.0000"
    assert product_metrics.json()["top_products"][0]["revenue"] == "200.0000"
    theory = client.get(
        "/api/v1/analytics/ingredient-consumption/theoretical?start_date=2026-11-25&end_date=2026-11-25",
        cookies={"stockpilot_session": token})
    assert theory.status_code == 200, theory.text
    coffee = next(item for item in theory.json()["items"] if item["ingredient_id"] == beans["id"])
    assert Decimal(coffee["total_theoretical_consumption"]) == Decimal("36")
    assert coffee["source_uploads"] == [{
        "upload_id": corrected.json()["id"], "version": corrected.json()["version"]
    }]

    listed_uploads = client.get("/api/v1/uploads", cookies={"stockpilot_session": token})
    assert listed_uploads.status_code == 200
    version_views = {item["id"]: item for item in listed_uploads.json()}
    assert version_views[uploaded.json()["id"]]["is_current"] is False
    assert version_views[corrected.json()["id"]]["is_current"] is True

    # A correction retry returns the completed current upload without
    # re-inserting its sales rows or modifier selections.
    assert process(client, token, corrected.json()["id"]).json()["processing_status"] == "COMPLETED"
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(SalesRecord)) == 2
        assert db.scalar(select(func.count()).select_from(SalesRecordModifier)) == 4


def test_correction_failure_after_structured_inserts_rolls_back(test_environment, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "upload_storage_dir", str(tmp_path))
    client, sessions = test_environment
    token = register_owner(client)
    branch_id = client.post("/api/v1/branches", cookies={"stockpilot_session": token}, json={
        "name": "Main", "code": "BR-001", "country_code": "IN", "timezone": "Asia/Kolkata",
    }).json()["id"]
    client.post("/api/v1/products", cookies={"stockpilot_session": token}, json={
        "sku": "SKU-001", "product_name": "Tea", "unit_of_measure": "EA",
    })
    first = create_upload(client, token, branch_id, workbook())
    assert process(client, token, first.json()["id"]).json()["processing_status"] == "COMPLETED"
    correction = create_upload(client, token, branch_id, workbook(net_amount=119, tax_amount=19))

    original_flush = Session.flush
    flush_count = 0

    def flush_then_fail_after_rows(db, *args, **kwargs):
        nonlocal flush_count
        flush_count += 1
        result = original_flush(db, *args, **kwargs)
        if flush_count == 2:
            raise RuntimeError("simulated failure after inventory and purchase inserts")
        return result

    monkeypatch.setattr(Session, "flush", flush_then_fail_after_rows)
    with pytest.raises(RuntimeError, match="simulated failure"):
        process(client, token, correction.json()["id"])

    with sessions() as db:
        current = db.scalar(select(DailyUpload).where(DailyUpload.is_current.is_(True)))
        assert current.id == UUID(first.json()["id"])
        failed_upload = db.get(DailyUpload, UUID(correction.json()["id"]))
        assert failed_upload.is_current is False
        assert_counts(db, 1, 1, 1)
        retained_sale = db.scalar(select(SalesRecord))
        assert retained_sale is not None
        assert retained_sale.source_upload_id == UUID(first.json()["id"])
        assert retained_sale.net_amount == Decimal("118")
        assert db.scalar(select(func.count()).select_from(InventorySnapshot).where(
            InventorySnapshot.source_upload_id == UUID(correction.json()["id"]))) == 0
        assert db.scalar(select(func.count()).select_from(PurchaseLine).where(
            PurchaseLine.source_upload_id == UUID(correction.json()["id"]))) == 0


def test_correction_retains_upload_evidence_and_moves_receipt_pointer(test_environment, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "upload_storage_dir", str(tmp_path))
    client, sessions = test_environment
    token = register_owner(client)
    branch_id = client.post("/api/v1/branches", cookies={"stockpilot_session": token}, json={
        "name": "Main", "code": "BR-001", "country_code": "IN", "timezone": "Asia/Kolkata",
    }).json()["id"]
    client.post("/api/v1/products", cookies={"stockpilot_session": token}, json={
        "sku": "SKU-001", "product_name": "Tea", "unit_of_measure": "EA",
    })
    first = create_upload(client, token, branch_id, workbook())
    assert process(client, token, first.json()["id"]).json()["processing_status"] == "COMPLETED"

    with sessions() as db:
        upload = db.get(DailyUpload, UUID(first.json()["id"]))
        old_line = db.scalar(select(PurchaseLine).where(PurchaseLine.source_upload_id == upload.id))
        identity = PurchaseReceiptIdentity(company_id=upload.company_id,
            branch_id=upload.branch_id, receipt_event_id="internal-event-001")
        db.add(identity)
        db.flush()
        old_line.receipt_identity_id = identity.id
        db.add(PurchaseReceiptCurrentLine(receipt_identity_id=identity.id,
            company_id=upload.company_id, branch_id=upload.branch_id,
            purchase_line_id=old_line.id))
        db.add(StockMovement(company_id=upload.company_id, branch_id=upload.branch_id,
            ingredient_product_id=old_line.product_id, movement_date=upload.business_date,
            movement_type="WASTE", quantity=Decimal("1"), unit="EA",
            source_upload_id=upload.id, origin_type="UPLOAD", physical_event_id=uuid4()))
        db.add(StockCoverageDeclaration(company_id=upload.company_id,
            branch_id=upload.branch_id, business_date=upload.business_date,
            source_upload_id=upload.id, ingredient_product_id=old_line.product_id,
            unit="EA", coverage_dimension="INGREDIENT", scope_type="INGREDIENT",
            status="COMPLETE"))
        db.commit()
        identity_id = identity.id
        old_line_id = old_line.id

    original_validations = upload_processing._validations

    def validations_with_internal_receipt_identity(db, upload, branch, content):
        result = original_validations(db, upload, branch, content)
        for row in result.rows.get("Purchases", []):
            row["__receipt_identity_id"] = str(identity_id)
        return result

    monkeypatch.setattr(upload_processing, "_validations", validations_with_internal_receipt_identity)
    second = create_upload(client, token, branch_id, workbook(net_amount=119, tax_amount=19))
    original_flush = Session.flush
    flush_count = 0

    def flush_then_fail_after_pointer_staging(db, *args, **kwargs):
        nonlocal flush_count
        flush_count += 1
        result = original_flush(db, *args, **kwargs)
        if flush_count == 3:
            raise RuntimeError("simulated promotion failure after pointer staging")
        return result

    monkeypatch.setattr(Session, "flush", flush_then_fail_after_pointer_staging)
    with pytest.raises(RuntimeError, match="after pointer staging"):
        process(client, token, second.json()["id"])
    with sessions() as db:
        assert db.get(PurchaseReceiptCurrentLine, identity_id).purchase_line_id == old_line_id
        assert db.scalar(select(DailyUpload).where(DailyUpload.is_current.is_(True))).id == UUID(first.json()["id"])
        assert_counts(db, 1, 1, 1)

    monkeypatch.setattr(Session, "flush", original_flush)
    assert process(client, token, second.json()["id"]).json()["processing_status"] == "COMPLETED"

    with sessions() as db:
        uploads = db.scalars(select(DailyUpload).order_by(DailyUpload.version)).all()
        assert [(row.version, row.is_current) for row in uploads] == [(1, False), (2, True)]
        old_line = db.get(PurchaseLine, old_line_id)
        new_line = db.scalar(select(PurchaseLine).where(
            PurchaseLine.source_upload_id == UUID(second.json()["id"])))
        assert old_line is not None and new_line is not None
        pointer = db.get(PurchaseReceiptCurrentLine, identity_id)
        assert pointer.purchase_line_id == new_line.id
        assert pointer.purchase_line_id != old_line.id
        assert db.scalar(select(func.count()).select_from(StockMovement).where(
            StockMovement.source_upload_id == UUID(first.json()["id"]))) == 1
        assert db.scalar(select(func.count()).select_from(StockCoverageDeclaration).where(
            StockCoverageDeclaration.source_upload_id == UUID(first.json()["id"]))) == 1
        assert db.scalar(select(func.count()).select_from(StockMovement).where(
            StockMovement.movement_type == "PURCHASE_RECEIPT")) == 0
        assert_counts(db, 2, 2, 2)

def test_historical_import_partial_failure_progress_and_retry(test_environment, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "upload_storage_dir", str(tmp_path))
    client, sessions = test_environment
    import app.api.routes.historical_imports as historical_imports
    monkeypatch.setattr(historical_imports, "SessionLocal", sessions)
    real_process_upload = historical_imports.process_upload
    token = register_owner(client)
    branch_one = client.post("/api/v1/branches", cookies={"stockpilot_session": token}, json={
        "name": "Main", "code": "BR-001", "country_code": "IN", "timezone": "Asia/Kolkata",
    }).json()["id"]
    branch_two = client.post("/api/v1/branches", cookies={"stockpilot_session": token}, json={
        "name": "Second", "code": "BR-002", "country_code": "IN", "timezone": "Asia/Kolkata",
    }).json()["id"]
    client.post("/api/v1/products", cookies={"stockpilot_session": token}, json={
        "sku": "SKU-001", "product_name": "Tea", "unit_of_measure": "EA",
    })

    # One-file historical import processes an upload that has not been processed yet.
    one_file = create_upload(client, token, branch_one,
        workbook(metadata_date="2026-11-25", business_date="2026-11-25"))
    single_job = client.post("/api/v1/historical-imports", cookies={"stockpilot_session": token}, json={"upload_ids": [one_file.json()["id"]]})
    single_status = client.get(f"/api/v1/historical-imports/{single_job.json()['id']}", cookies={"stockpilot_session": token}).json()
    assert single_status["status"] == "COMPLETED"
    assert (single_status["total_files"], single_status["completed_files"], single_status["failed_files"]) == (1, 1, 0)
    assert single_status["files"][0]["status"] == "COMPLETED"

    # Multiple files span dates and branches; one transient failure does not fail its sibling.
    good = create_upload(client, token, branch_one,
        workbook(metadata_date="2026-11-26", business_date="2026-11-26"), business_date="2026-11-26")
    transient_failure = create_upload(client, token, branch_two,
        workbook(metadata_date="2026-11-27", business_date="2026-11-27", branch_reference="BR-002"), business_date="2026-11-27")
    failed_id = transient_failure.json()["id"]

    def fail_one_file(db, upload, branch, content):
        if str(upload.id) == failed_id:
            raise RuntimeError("Simulated transient processing failure")
        return real_process_upload(db, upload, branch, content)

    monkeypatch.setattr(historical_imports, "process_upload", fail_one_file)
    multi_job = client.post("/api/v1/historical-imports", cookies={"stockpilot_session": token}, json={
        "upload_ids": [good.json()["id"], failed_id],
    })
    assert multi_job.status_code == 202
    detail = client.get(f"/api/v1/historical-imports/{multi_job.json()['id']}", cookies={"stockpilot_session": token}).json()
    assert detail["status"] == "PARTIAL_FAILED"
    assert (detail["total_files"], detail["completed_files"], detail["failed_files"], detail["skipped_files"]) == (2, 1, 1, 0)
    assert detail["progress_percent"] == 100
    assert {entry["status"] for entry in detail["files"]} == {"COMPLETED", "FAILED"}

    monkeypatch.setattr(historical_imports, "process_upload", real_process_upload)
    retry = client.post(f"/api/v1/historical-imports/{multi_job.json()['id']}/retry", cookies={"stockpilot_session": token})
    assert retry.status_code == 202
    retried = client.get(f"/api/v1/historical-imports/{multi_job.json()['id']}", cookies={"stockpilot_session": token}).json()
    assert retried["status"] == "COMPLETED"
    assert (retried["total_files"], retried["completed_files"], retried["failed_files"]) == (2, 2, 0)
    assert {entry["status"] for entry in retried["files"]} == {"COMPLETED"}
    with sessions() as db:
        assert_counts(db, 3, 3, 3)

    duplicate_selection = client.post("/api/v1/historical-imports", cookies={"stockpilot_session": token}, json={
        "upload_ids": [one_file.json()["id"], one_file.json()["id"]],
    })
    assert duplicate_selection.status_code == 422


def test_upload_and_import_routes_enforce_company_branch_and_role_access(test_environment, tmp_path, monkeypatch):
    from uuid import UUID

    client, sessions = test_environment
    monkeypatch.setattr(settings, "upload_storage_dir", str(tmp_path))
    owner_token = register_owner(client)
    profile = client.get("/api/v1/auth/me", cookies={"stockpilot_session": owner_token}).json()
    company_id = UUID(profile["company_id"])
    branch_one = client.post("/api/v1/branches", cookies={"stockpilot_session": owner_token}, json={
        "name": "Assigned", "code": "BR-001", "country_code": "IN", "timezone": "Asia/Kolkata",
    }).json()["id"]
    branch_two = client.post("/api/v1/branches", cookies={"stockpilot_session": owner_token}, json={
        "name": "Unassigned", "code": "BR-002", "country_code": "IN", "timezone": "Asia/Kolkata",
    }).json()["id"]
    owner_upload = create_upload(client, owner_token, branch_one, workbook())
    other_branch_upload = create_upload(client, owner_token, branch_two,
        workbook(branch_reference="BR-002"))
    assert owner_upload.status_code == 201 and other_branch_upload.status_code == 201

    with sessions() as db:
        manager = User(full_name="Manager", email="manager@example.com",
            password_hash=hash_password("StockPilot_Manager_123!"), is_active=True)
        staff = User(full_name="Staff", email="staff@example.com",
            password_hash=hash_password("StockPilot_Staff_123!"), is_active=True)
        analyst = User(full_name="Analyst", email="analyst@example.com",
            password_hash=hash_password("StockPilot_Analyst_123!"), is_active=True)
        db.add_all([manager, staff, analyst]); db.flush()
        memberships = [CompanyMembership(company_id=company_id, user_id=user.id, role=role)
            for user, role in ((manager, "MANAGER"), (staff, "STAFF"), (analyst, "ANALYST"))]
        db.add_all(memberships); db.flush()
        db.add(BranchMembership(branch_id=UUID(branch_one), company_membership_id=memberships[0].id))
        db.commit()

    def login(email, password):
        return client.post("/api/v1/auth/login", json={"email": email, "password": password}).cookies.get("stockpilot_session")

    manager_token = login("manager@example.com", "StockPilot_Manager_123!")
    manager_uploads = client.get("/api/v1/uploads", cookies={"stockpilot_session": manager_token})
    assert manager_uploads.status_code == 200
    assert {entry["id"] for entry in manager_uploads.json()} == {owner_upload.json()["id"]}
    assert client.get(f"/api/v1/uploads/{other_branch_upload.json()['id']}/processing-status", cookies={"stockpilot_session": manager_token}).status_code == 403
    assert client.post("/api/v1/historical-imports", cookies={"stockpilot_session": manager_token}, json={
        "upload_ids": [other_branch_upload.json()["id"]],
    }).status_code == 403

    # A different company cannot inspect or import another tenant's workbook.
    client.post("/api/v1/auth/register", json={
        "full_name": "Other Owner", "email": "other-owner@example.com",
        "password": "StockPilot_Test_123!", "company_name": "Other Company",
        "industry": "grocery", "country_code": "IN", "currency": "INR", "timezone": "Asia/Kolkata",
    })
    other_token = client.post("/api/v1/auth/login", json={
        "email": "other-owner@example.com", "password": "StockPilot_Test_123!",
    }).cookies.get("stockpilot_session")
    assert client.get(f"/api/v1/uploads/{owner_upload.json()['id']}/processing-status", cookies={"stockpilot_session": other_token}).status_code == 404
    assert client.post("/api/v1/historical-imports", cookies={"stockpilot_session": other_token}, json={
        "upload_ids": [owner_upload.json()["id"]],
    }).status_code == 404

    for email, password in (("staff@example.com", "StockPilot_Staff_123!"),
                            ("analyst@example.com", "StockPilot_Analyst_123!")):
        token = login(email, password)
        assert client.get("/api/v1/uploads", cookies={"stockpilot_session": token}).status_code == 403
        assert client.post("/api/v1/historical-imports", cookies={"stockpilot_session": token}, json={
            "upload_ids": [owner_upload.json()["id"]],
        }).status_code == 403
