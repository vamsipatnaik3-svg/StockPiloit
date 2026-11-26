from datetime import date
from decimal import Decimal
from io import BytesIO
from uuid import UUID, uuid4

from openpyxl import Workbook
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import (Branch, CompanyMembership, DailyUpload, InventorySnapshot,
    Product, PurchaseLine, PurchaseReceiptCurrentLine, PurchaseReceiptIdentity,
    SalesRecord, StockCoverageDeclaration, StockMovement, StockMovementReasonCode,
    User)


MOVEMENT_A = "50d050d0-0000-4000-8000-000000000001"
MOVEMENT_B = "50d050d0-0000-4000-8000-000000000002"
RECEIPT_A = "physical-delivery-2026-11-25-a"
RECEIPT_B = "physical-delivery-2026-11-25-b"


def v3_workbook(*, quantity_a="2", waste_quantity="0.5", movement_type="WASTE",
        receipt_event_a=RECEIPT_A, receipt_event_b=RECEIPT_B,
        movement_id_a=MOVEMENT_A, movement_id_b=MOVEMENT_B,
        movement_sku="ING-001", movement_unit="g", movement_date="2026-11-25",
        movement_reason="WASTE_SPOILAGE", coverage_status="COMPLETE",
        duplicate_event=False, include_coverage=True, business_date="2026-11-25",
        coverage_extra=(), purchase_unit="g"):
    wb = Workbook()
    metadata = wb.active
    metadata.title = "Metadata"
    for row in [("Field", "Value"), ("Template Version", "3.0"),
        ("Business Date", business_date), ("Branch Reference", "BR-001"),
        ("Currency", "INR"), ("Source Granularity", "AGGREGATED")]:
        metadata.append(row)
    sales = wb.create_sheet("Daily Sales")
    sales.append(["Transaction ID", "Line ID", "Transaction DateTime", "SKU", "Quantity",
        "Unit Selling Price", "Discount Amount", "Tax Amount", "Net Amount", "Source Reference",
        "Aggregate ID", "Sales Row Reference", "Sales Channel"])
    inventory = wb.create_sheet("Inventory")
    inventory.append(["SKU", "Batch Number", "Opening Quantity", "Closing Quantity", "Unit",
        "Expiry Date", "Unit Cost", "Damaged Quantity", "Wasted Quantity", "Adjustment Quantity",
        "Adjustment Reason", "Staff Consumption Quantity"])
    inventory.append(["ING-001", "BATCH-1", 10, 9, "g", None, 2, 0, 0, 0, None, 0])
    inventory.append(["ING-001", "BATCH-2", 5, 4, "g", None, 2, 0, 0, 0, None, 0])
    purchases = wb.create_sheet("Purchases")
    purchases.append(["Receipt ID", "Receipt Line ID", "Receipt Date", "Supplier Name", "SKU",
        "Quantity Received", "Unit Purchase Price", "Batch Number", "Expiry Date", "Purchase Unit",
        "Receipt Event ID"])
    purchases.append(["INV-77", "LINE-4", business_date, "Supplier", "ING-001",
        quantity_a, 3, "BATCH-1", None, purchase_unit, receipt_event_a])
    purchases.append(["INV-77", "LINE-4", business_date, "Supplier", "ING-001",
        3, 3, "BATCH-2", None, purchase_unit, receipt_event_b])
    modifiers = wb.create_sheet("Sales Modifiers")
    modifiers.append(["Sales Row Reference", "Modifier Group", "Modifier Option", "Selection Quantity"])
    movements = wb.create_sheet("Stock Movements")
    movements.append(["Physical Event ID", "Movement Date", "Ingredient SKU", "Movement Type",
        "Quantity", "Unit", "Batch Number", "Reason Code", "Reason Detail"])
    movements.append([movement_id_a, movement_date, movement_sku, movement_type,
        waste_quantity, movement_unit, "BATCH-1", movement_reason,
        "Adjustment correction" if movement_type in {"POSITIVE_ADJUSTMENT", "NEGATIVE_ADJUSTMENT"} else None])
    movements.append([movement_id_b if not duplicate_event else movement_id_a, business_date,
        "ING-001", "OTHER_INFLOW", 1, "g", "BATCH-2", "OTHER_INFLOW_REASON", "Store return"])
    coverage = wb.create_sheet("Stock Coverage")
    coverage.append(["Ingredient SKU", "Coverage Dimension", "Scope Type", "Batch Number",
        "Movement Type", "Status", "Unit"])
    if include_coverage:
        coverage.append(["ING-001", "INGREDIENT", "INGREDIENT", None, None, coverage_status, "g"])
        coverage.append(["ING-002", "INGREDIENT", "INGREDIENT", None, None, "NO_STOCK", "ml"])
        coverage.append(["ING-003", "INGREDIENT", "INGREDIENT", None, None, "UNREPORTED", "pcs"])
        coverage.append(["ING-001", "CLOSING_STOCK", "BATCH", "BATCH-1", None, "COMPLETE", "g"])
        coverage.append(["ING-001", "MOVEMENT_CATEGORY", "BATCH", "BATCH-1", "WASTE", "PARTIAL", "g"])
        for extra in coverage_extra:
            coverage.append(list(extra))
    output = BytesIO()
    wb.save(output)
    return output.getvalue()


def register_owner(client):
    email = "v3-owner@example.com"
    client.post("/api/v1/auth/register", json={
        "full_name": "V3 Owner", "email": email, "password": "StockPilot_Test_123!",
        "company_name": "V3 Company", "industry": "grocery", "country_code": "IN",
        "currency": "INR", "timezone": "Asia/Kolkata",
    })
    login = client.post("/api/v1/auth/login", json={
        "email": email, "password": "StockPilot_Test_123!",
    })
    return login.cookies.get("stockpilot_session")


def setup_v3(client, sessions, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "upload_storage_dir", str(tmp_path))
    token = register_owner(client)
    branch = client.post("/api/v1/branches", cookies={"stockpilot_session": token}, json={
        "name": "Main", "code": "BR-001", "country_code": "IN", "timezone": "Asia/Kolkata",
    }).json()
    products = []
    for sku, name, unit in [("ING-001", "Beans", "g"), ("ING-002", "Milk", "ml"),
                            ("ING-003", "Croissant", "pcs"),
                            ("MENU-001", "Cappuccino", "pcs"),
                            ("LEGACY-001", "Unclassified product", "EA")]:
        response = client.post("/api/v1/products", cookies={"stockpilot_session": token}, json={
            "sku": sku, "product_name": name, "unit_of_measure": unit,
            **({"product_kind": "INGREDIENT"} if sku.startswith("ING-") else
               {"product_kind": "MENU_ITEM"} if sku.startswith("MENU-") else {}),
        })
        assert response.status_code == 201, response.text
        products.append(response.json())
    with sessions() as db:
        db.add_all([
            StockMovementReasonCode(code="RECEIVED_FROM_SUPPLIER", movement_type="PURCHASE_RECEIPT", label="Supplier receipt"),
            StockMovementReasonCode(code="WASTE_SPOILAGE", movement_type="WASTE", label="Spoilage"),
            StockMovementReasonCode(code="OTHER_INFLOW_REASON", movement_type="OTHER_INFLOW", label="Other inflow"),
            StockMovementReasonCode(code="POSITIVE_COUNT_CORRECTION", movement_type="POSITIVE_ADJUSTMENT", label="Count correction"),
        ])
        db.commit()
    return {"token": token, "branch": branch, "products": products}


def upload(client, ctx, content, business_date="2026-11-25"):
    return client.post("/api/v1/uploads", data={
        "branch_id": ctx["branch"]["id"], "business_date": business_date,
    }, files={"file": ("daily-v3.xlsx", content,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        cookies={"stockpilot_session": ctx["token"]})


def process(client, ctx, upload_id):
    return client.post(f"/api/v1/uploads/{upload_id}/process",
        cookies={"stockpilot_session": ctx["token"]})


def test_v3_purchase_partial_events_movements_coverage_correction_and_retry(test_environment, tmp_path, monkeypatch):
    client, sessions = test_environment
    ctx = setup_v3(client, sessions, tmp_path, monkeypatch)
    first = upload(client, ctx, v3_workbook())
    assert first.status_code == 201, first.text
    processed = process(client, ctx, first.json()["id"])
    assert processed.status_code == 200 and processed.json()["processing_status"] == "COMPLETED", processed.text

    with sessions() as db:
        old_lines = db.scalars(select(PurchaseLine).where(
            PurchaseLine.source_upload_id == UUID(first.json()["id"])).order_by(PurchaseLine.id)).all()
        assert len(old_lines) == 2
        assert len({line.receipt_identity_id for line in old_lines}) == 2
        old_line_ids = {line.id for line in old_lines}
        identities = {line.receipt_identity_id for line in old_lines}
        purchases = db.scalars(select(StockMovement).where(
            StockMovement.source_upload_id == UUID(first.json()["id"]),
            StockMovement.movement_type == "PURCHASE_RECEIPT")).all()
        assert len(purchases) == 2
        assert {movement.purchase_line_id for movement in purchases} == old_line_ids
        assert {movement.physical_event_id for movement in purchases} == identities
        assert all(movement.origin_type == "UPLOAD" and movement.movement_date == date(2026, 11, 25)
            and movement.unit == "g" for movement in purchases)
        manual_source_movements = db.scalars(select(StockMovement).where(
            StockMovement.source_upload_id == UUID(first.json()["id"]),
            StockMovement.movement_type != "PURCHASE_RECEIPT")).all()
        assert {movement.movement_type for movement in manual_source_movements} == {"WASTE", "OTHER_INFLOW"}
        assert db.scalar(select(func.count()).select_from(StockCoverageDeclaration).where(
            StockCoverageDeclaration.source_upload_id == UUID(first.json()["id"]))) == 5
        status_by_product = {str(row.ingredient_product_id): row.status for row in
            db.scalars(select(StockCoverageDeclaration).where(
                StockCoverageDeclaration.source_upload_id == UUID(first.json()["id"]),
                StockCoverageDeclaration.coverage_dimension == "INGREDIENT")).all()}
        assert status_by_product[ctx["products"][0]["id"]] == "COMPLETE"
        assert status_by_product[ctx["products"][1]["id"]] == "NO_STOCK"
        assert status_by_product[ctx["products"][2]["id"]] == "UNREPORTED"
        old_pointer = {pointer.receipt_identity_id: pointer.purchase_line_id for pointer in
            db.scalars(select(PurchaseReceiptCurrentLine)).all()}
        assert set(old_pointer) == identities

    # Same upload ID is a no-op retry.
    assert process(client, ctx, first.json()["id"]).json()["processing_status"] == "COMPLETED"
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(StockMovement)) == 4
        assert db.scalar(select(func.count()).select_from(StockCoverageDeclaration)) == 5

    second = upload(client, ctx, v3_workbook(quantity_a="4", waste_quantity="0.75"))
    assert second.status_code == 201
    assert process(client, ctx, second.json()["id"]).json()["processing_status"] == "COMPLETED"
    with sessions() as db:
        old_upload = db.get(DailyUpload, UUID(first.json()["id"]))
        new_upload = db.get(DailyUpload, UUID(second.json()["id"]))
        assert old_upload.is_current is False and new_upload.is_current is True
        assert db.scalar(select(func.count()).select_from(StockMovement)) == 8
        assert db.scalar(select(func.count()).select_from(StockCoverageDeclaration)) == 10
        latest_lines = db.scalars(select(PurchaseLine).where(
            PurchaseLine.source_upload_id == new_upload.id)).all()
        latest_by_identity = {line.receipt_identity_id: line.id for line in latest_lines}
        pointers = {pointer.receipt_identity_id: pointer.purchase_line_id for pointer in
            db.scalars(select(PurchaseReceiptCurrentLine)).all()}
        assert pointers == latest_by_identity
        assert not set(pointers.values()).intersection(old_line_ids)

    assert process(client, ctx, second.json()["id"]).json()["processing_status"] == "COMPLETED"
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(StockMovement)) == 8
        assert db.scalar(select(func.count()).select_from(StockCoverageDeclaration)) == 10


@pytest.mark.parametrize(("override", "issue_code"), [
    ({"receipt_event_a": ""}, "MISSING_RECEIPT_EVENT_ID"),
    ({"receipt_event_b": RECEIPT_A}, "DUPLICATE_RECEIPT_EVENT_ID"),
    ({"movement_type": "PURCHASE_RECEIPT"}, "INVALID_MOVEMENT_TYPE"),
    ({"movement_type": "TRANSFER_IN"}, "INVALID_MOVEMENT_TYPE"),
    ({"movement_sku": "NOT-FOUND"}, "UNKNOWN_SKU"),
    ({"movement_sku": "MENU-001"}, "INCORRECT_PRODUCT_KIND"),
    ({"movement_sku": "LEGACY-001"}, "INCORRECT_PRODUCT_KIND"),
    ({"movement_sku": "ING-002", "movement_unit": "g"}, "UNIT_MISMATCH"),
    ({"movement_unit": "kg"}, "UNIT_MISMATCH"),
    ({"waste_quantity": "0"}, "INVALID_MOVEMENT_QUANTITY"),
    ({"waste_quantity": "0.00001"}, "INVALID_MOVEMENT_QUANTITY_PRECISION"),
    ({"purchase_unit": "kg"}, "UNIT_MISMATCH"),
    ({"quantity_a": "0.00001"}, "INVALID_PURCHASE_QUANTITY_PRECISION"),
    ({"movement_date": "2026-11-24"}, "MOVEMENT_DATE_MISMATCH"),
    ({"movement_reason": "DAMAGE_STORAGE"}, "INVALID_MOVEMENT_REASON"),
    ({"duplicate_event": True}, "DUPLICATE_PHYSICAL_EVENT_ID"),
    ({"movement_id_a": "not-a-uuid"}, "INVALID_PHYSICAL_EVENT_ID"),
    ({"coverage_status": "UNKNOWN"}, "INVALID_COVERAGE_STATUS"),
    ({"coverage_extra": [("ING-001", "INGREDIENT", "INGREDIENT", None, None, "PARTIAL", "g")]}, "DUPLICATE_COVERAGE_DECLARATION"),
    ({"coverage_extra": [("ING-001", "CLOSING_STOCK", "INGREDIENT", None, None, "COMPLETE", "g")]}, "CONTRADICTORY_COVERAGE_SCOPE"),
    ({"coverage_extra": [("ING-001", "INGREDIENT", "INGREDIENT", None, None, "NO_STOCK", "g")]}, "CONTRADICTORY_NO_STOCK"),
    ({"coverage_extra": [("ING-001", "CLOSING_STOCK", "BATCH", "MISSING-BATCH", None, "PARTIAL", "g")]}, "UNKNOWN_COVERAGE_BATCH"),
])
def test_v3_invalid_stock_or_receipt_rows_are_rejected_without_becoming_zero(
        test_environment, tmp_path, monkeypatch, override, issue_code):
    client, _sessions = test_environment
    ctx = setup_v3(client, _sessions, tmp_path, monkeypatch)
    uploaded = upload(client, ctx, v3_workbook(**override))
    assert uploaded.status_code == 201
    result = process(client, ctx, uploaded.json()["id"])
    assert result.json()["processing_status"] == "VALIDATION_FAILED"
    report = client.get(f"/api/v1/uploads/{uploaded.json()['id']}/validation-report",
        cookies={"stockpilot_session": ctx["token"]}).json()
    assert issue_code in {issue["code"] for issue in report["issues"]}
    with _sessions() as db:
        assert db.scalar(select(func.count()).select_from(StockMovement)) == 0
        assert db.scalar(select(func.count()).select_from(PurchaseLine)) == 0
        assert db.scalar(select(func.count()).select_from(PurchaseReceiptIdentity)) == 0
        assert db.scalar(select(func.count()).select_from(StockCoverageDeclaration)) == 0


def test_v3_failed_correction_rolls_back_movement_coverage_and_receipt_pointer_changes(
        test_environment, tmp_path, monkeypatch):
    client, sessions = test_environment
    ctx = setup_v3(client, sessions, tmp_path, monkeypatch)
    first = upload(client, ctx, v3_workbook())
    assert process(client, ctx, first.json()["id"]).json()["processing_status"] == "COMPLETED"
    second = upload(client, ctx, v3_workbook(quantity_a="5", waste_quantity="0.8"))

    original_flush = Session.flush
    original_commit = Session.commit

    def flush_then_fail(session, *args, **kwargs):
        original_flush(session)
        raise RuntimeError("simulated failure before promotion")

    monkeypatch.setattr(Session, "commit", flush_then_fail)
    with pytest.raises(RuntimeError, match="before promotion"):
        process(client, ctx, second.json()["id"])
    monkeypatch.setattr(Session, "commit", original_commit)
    with sessions() as db:
        assert db.scalar(select(DailyUpload).where(DailyUpload.is_current.is_(True))).id == UUID(first.json()["id"])
        assert db.scalar(select(func.count()).select_from(StockMovement)) == 4
        assert db.scalar(select(func.count()).select_from(StockCoverageDeclaration)) == 5
        current_lines = db.scalars(select(PurchaseLine).where(
            PurchaseLine.source_upload_id == UUID(first.json()["id"]))).all()
        current_ids = {line.id for line in current_lines}
        assert {pointer.purchase_line_id for pointer in db.scalars(select(PurchaseReceiptCurrentLine)).all()} == current_ids


def test_event_ids_cannot_be_reused_for_a_different_upload_date(test_environment, tmp_path, monkeypatch):
    client, sessions = test_environment
    ctx = setup_v3(client, sessions, tmp_path, monkeypatch)
    first = upload(client, ctx, v3_workbook())
    assert process(client, ctx, first.json()["id"]).json()["processing_status"] == "COMPLETED"
    later = upload(client, ctx, v3_workbook(business_date="2026-11-26",
        movement_date="2026-11-26", movement_id_a="60d060d0-0000-4000-8000-000000000001",
        movement_id_b="60d060d0-0000-4000-8000-000000000002"), business_date="2026-11-26")
    assert later.status_code == 201
    result = process(client, ctx, later.json()["id"])
    assert result.json()["processing_status"] == "VALIDATION_FAILED"
    report = client.get(f"/api/v1/uploads/{later.json()['id']}/validation-report",
        cookies={"stockpilot_session": ctx["token"]}).json()
    assert "RECEIPT_EVENT_ID_REUSED" in {issue["code"] for issue in report["issues"]}
    assert "PHYSICAL_EVENT_ID_REUSED" not in {issue["code"] for issue in report["issues"]}
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(PurchaseLine)) == 2
        assert db.scalar(select(func.count()).select_from(StockMovement)) == 4
