from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import func, select

from app.core.security import hash_password
from app.models import (Branch, BranchMembership, CompanyMembership, DailyUpload,
    InventorySnapshot, Product, PurchaseLine, PurchaseReceiptConfirmation,
    PurchaseReceiptCurrentLine, PurchaseReceiptIdentity, StockCountLine,
    StockCountSubmission, StockMovement, StockMovementReasonCode, User)


PASSWORD = "StockPilot_StaffOps_123!"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def setup_staff_operations(client, sessions, suffix="a"):
    email = f"staff-ops-owner-{suffix}@example.com"
    registration = client.post("/api/v1/auth/register", json={
        "full_name": "Operations Owner", "email": email, "password": PASSWORD,
        "company_name": f"Operations {suffix}", "industry": "grocery",
        "country_code": "IN", "currency": "INR", "timezone": "Asia/Kolkata",
    })
    assert registration.status_code == 201, registration.text
    company_id = UUID(registration.json()["company_id"])
    login = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    owner_token = login.cookies.get("stockpilot_session")
    branches = []
    for code in (f"A{suffix.upper()}", f"B{suffix.upper()}"):
        result = client.post("/api/v1/branches", cookies={"stockpilot_session": owner_token},
            json={"name": f"Branch {code}", "code": code, "country_code": "IN",
                "timezone": "Asia/Kolkata"})
        assert result.status_code == 201, result.text
        branches.append(UUID(result.json()["id"]))
    ingredient = client.post("/api/v1/products", cookies={"stockpilot_session": owner_token},
        json={"sku": f"BEAN-{suffix}", "product_name": "Coffee beans",
            "unit_of_measure": "g", "product_kind": "INGREDIENT"}).json()
    menu = client.post("/api/v1/products", cookies={"stockpilot_session": owner_token},
        json={"sku": f"LATTE-{suffix}", "product_name": "Latte",
            "unit_of_measure": "pcs", "product_kind": "MENU_ITEM"}).json()
    with sessions() as db:
        owner_member = db.scalar(select(CompanyMembership).where(
            CompanyMembership.company_id == company_id, CompanyMembership.role == "OWNER"))
        staff_user = User(full_name="Count Staff", email=f"staff-{suffix}@example.com",
            password_hash=hash_password(PASSWORD), is_active=True)
        analyst_user = User(full_name="Read Analyst", email=f"analyst-{suffix}@example.com",
            password_hash=hash_password(PASSWORD), is_active=True)
        manager_user = User(full_name="Branch Manager", email=f"manager-{suffix}@example.com",
            password_hash=hash_password(PASSWORD), is_active=True)
        db.add_all([staff_user, analyst_user, manager_user]); db.flush()
        staff = CompanyMembership(company_id=company_id, user_id=staff_user.id, role="STAFF")
        analyst = CompanyMembership(company_id=company_id, user_id=analyst_user.id, role="ANALYST")
        manager = CompanyMembership(company_id=company_id, user_id=manager_user.id, role="MANAGER")
        db.add_all([staff, analyst, manager]); db.flush()
        db.add_all([BranchMembership(branch_id=branches[0], company_membership_id=staff.id),
            BranchMembership(branch_id=branches[0], company_membership_id=manager.id)])
        for code, movement_type, label in [
            ("WASTE_SPOILAGE", "WASTE", "Spoilage"),
            ("DAMAGE_STORAGE", "DAMAGE", "Storage damage"),
            ("RECEIVED_FROM_SUPPLIER", "PURCHASE_RECEIPT", "Supplier receipt"),
        ]:
            if db.get(StockMovementReasonCode, (code, movement_type)) is None:
                db.add(StockMovementReasonCode(code=code, movement_type=movement_type, label=label))
        db.flush()
        product = db.get(Product, UUID(ingredient["id"]))
        upload = DailyUpload(company_id=company_id, branch_id=branches[0],
            business_date=date(2026, 11, 25), uploaded_by_membership_id=owner_member.id,
            object_key=f"test/{uuid4()}", original_filename="receipts.xlsx",
            content_type=XLSX, file_size_bytes=100, version=1, status="UPLOADED",
            is_current=True, processing_status="COMPLETED")
        db.add(upload); db.flush()
        identity = PurchaseReceiptIdentity(company_id=company_id, branch_id=branches[0],
            receipt_event_id=f"EVENT-{suffix}")
        db.add(identity); db.flush()
        line = PurchaseLine(company_id=company_id, branch_id=branches[0],
            source_upload_id=upload.id, product_id=product.id, receipt_id=f"R-{suffix}",
            receipt_line_id="1", business_date=upload.business_date,
            receipt_date=upload.business_date, supplier_name="Supplier",
            quantity_received=Decimal("5"), unit_purchase_price=Decimal("2"),
            purchase_unit="g", batch_number="BATCH-1", receipt_identity_id=identity.id)
        db.add(line); db.flush()
        current_line = PurchaseReceiptCurrentLine(receipt_identity_id=identity.id,
            company_id=company_id, branch_id=branches[0], purchase_line_id=line.id)
        db.add(current_line)
        receipt_movement = StockMovement(company_id=company_id, branch_id=branches[0],
            ingredient_product_id=product.id, movement_date=upload.business_date,
            movement_type="PURCHASE_RECEIPT", quantity=line.quantity_received,
            unit="g", batch_number=line.batch_number, source_upload_id=upload.id,
            purchase_line_id=line.id, transfer_id=None, origin_type="UPLOAD",
            physical_event_id=identity.id, source_reference=identity.receipt_event_id,
            reason_code="RECEIVED_FROM_SUPPLIER", created_by_user_id=None)
        db.add(receipt_movement); db.commit()
        staff_id, analyst_id, manager_id = staff.id, analyst.id, manager.id

    staff_login = client.post("/api/v1/auth/login", json={
        "email": f"staff-{suffix}@example.com", "password": PASSWORD})
    analyst_login = client.post("/api/v1/auth/login", json={
        "email": f"analyst-{suffix}@example.com", "password": PASSWORD})
    manager_login = client.post("/api/v1/auth/login", json={
        "email": f"manager-{suffix}@example.com", "password": PASSWORD})
    return {"company_id": company_id, "owner_token": owner_token,
        "staff_token": staff_login.cookies.get("stockpilot_session"),
        "analyst_token": analyst_login.cookies.get("stockpilot_session"),
        "manager_token": manager_login.cookies.get("stockpilot_session"),
        "staff_id": staff_id, "analyst_id": analyst_id, "manager_id": manager_id,
        "branch": branches[0], "other_branch": branches[1],
        "ingredient": UUID(ingredient["id"]), "menu": UUID(menu["id"]),
        "identity": identity.id, "purchase_line": line.id,
        "upload": upload.id, "receipt_movement": receipt_movement.id}


def test_staff_stock_counts_are_scoped_idempotent_immutable_and_do_not_adjust_inventory(test_environment):
    client, sessions = test_environment
    ctx = setup_staff_operations(client, sessions)
    foreign = setup_staff_operations(client, sessions, "foreign-count")
    body = {"branch_id": str(ctx["branch"]), "counted_at": "2026-11-25T18:00:00+05:30",
        "idempotency_key": str(uuid4()), "lines": [{
            "ingredient_product_id": str(ctx["ingredient"]), "quantity": "0",
            "unit": "g", "batch_number": "BATCH-1"}]}
    response = client.post("/api/v1/staff-operations/stock-counts",
        cookies={"stockpilot_session": ctx["staff_token"]}, json=body)
    assert response.status_code == 201, response.text
    first_id = response.json()["id"]
    assert response.json()["status"] == "SUBMITTED"
    assert response.json()["submitted_by_membership_id"] == str(ctx["staff_id"])
    assert response.json()["lines"][0]["quantity"] == "0.0000"
    retry = client.post("/api/v1/staff-operations/stock-counts",
        cookies={"stockpilot_session": ctx["staff_token"]}, json=body)
    assert retry.status_code == 200 and retry.json()["id"] == first_id
    conflict = {**body, "lines": [{**body["lines"][0], "quantity": "1"}]}
    assert client.post("/api/v1/staff-operations/stock-counts",
        cookies={"stockpilot_session": ctx["staff_token"]}, json=conflict).status_code == 409

    correction = {**body, "idempotency_key": str(uuid4()),
        "corrects_submission_id": first_id,
        "lines": [{**body["lines"][0], "quantity": "3.25"}]}
    corrected = client.post("/api/v1/staff-operations/stock-counts",
        cookies={"stockpilot_session": ctx["staff_token"]}, json=correction)
    assert corrected.status_code == 201, corrected.text
    listed = client.get("/api/v1/staff-operations/stock-counts",
        cookies={"stockpilot_session": ctx["staff_token"]})
    assert listed.status_code == 200 and listed.json()["total"] == 2
    assert any(item["corrects_submission_id"] == first_id
        for item in listed.json()["items"])
    assert client.get(f"/api/v1/staff-operations/stock-counts/{first_id}",
        cookies={"stockpilot_session": ctx["staff_token"]}).status_code == 200
    assert client.get("/api/v1/staff-operations/stock-counts",
        cookies={"stockpilot_session": ctx["owner_token"]}).json()["total"] == 2

    bad_inputs = [
        {**body, "idempotency_key": str(uuid4()), "lines": [
            {**body["lines"][0], "quantity": "-1"}]},
        {**body, "idempotency_key": str(uuid4()), "lines": [
            {**body["lines"][0], "unit": "kg"}]},
        {**body, "idempotency_key": str(uuid4()), "lines": [
            {**body["lines"][0], "ingredient_product_id": str(ctx["menu"])}]},
        {**body, "idempotency_key": str(uuid4()), "lines": [
            {**body["lines"][0], "ingredient_product_id": str(foreign["ingredient"])}]},
        {**body, "idempotency_key": str(uuid4()), "branch_id": str(ctx["other_branch"])},
    ]
    assert client.post("/api/v1/staff-operations/stock-counts",
        cookies={"stockpilot_session": ctx["staff_token"]}, json={**body,
            "idempotency_key": str(uuid4()), "counted_at": "2026-11-25T18:00:00"}).status_code == 422
    for bad in bad_inputs:
        result = client.post("/api/v1/staff-operations/stock-counts",
            cookies={"stockpilot_session": ctx["staff_token"]}, json=bad)
        assert result.status_code in {404, 422}, result.text
    assert client.get("/api/v1/analytics/overview",
        cookies={"stockpilot_session": ctx["staff_token"]}).status_code == 403
    assert client.post("/api/v1/staff-operations/stock-counts",
        cookies={"stockpilot_session": ctx["analyst_token"]}, json=body).status_code == 403
    assert client.post("/api/v1/staff-operations/stock-counts",
        cookies={"stockpilot_session": ctx["manager_token"]}, json=body).status_code == 403
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(StockCountSubmission)) == 2
        assert db.scalar(select(func.count()).select_from(StockCountLine)) == 2
        assert db.scalar(select(func.count()).select_from(InventorySnapshot)) == 0
        # Count submission does not add a stock movement or adjust the receipt.
        assert db.scalar(select(func.count()).select_from(StockMovement).where(
            StockMovement.company_id == ctx["company_id"])) == 1


def test_staff_waste_damage_uses_existing_ledger_idempotency_and_no_void_workflow(test_environment):
    client, sessions = test_environment
    ctx = setup_staff_operations(client, sessions, "w")
    foreign = setup_staff_operations(client, sessions, "foreign-waste")
    headers = {"stockpilot_session": ctx["staff_token"]}
    body = {"branch_id": str(ctx["branch"]), "ingredient_product_id": str(ctx["ingredient"]),
        "movement_type": "WASTE", "occurred_at": "2026-11-25T20:30:00+05:30",
        "idempotency_key": str(uuid4()), "quantity": "2.5", "unit": "g",
        "batch_number": "BATCH-1", "reason_code": "WASTE_SPOILAGE", "notes": "Expired beans"}
    created = client.post("/api/v1/staff-operations/waste-events", cookies=headers, json=body)
    assert created.status_code == 201, created.text
    event = created.json()
    assert event["movement_type"] == "WASTE"
    assert event["created_by_user_id"]
    assert event["movement_date"] == "2026-11-25"
    assert event["occurred_at"].startswith("2026-11-25T15:00:00")
    assert event["reason_detail"] == "Expired beans"
    retry = client.post("/api/v1/staff-operations/waste-events", cookies=headers, json=body)
    assert retry.status_code == 200 and retry.json()["id"] == event["id"]
    mismatch = client.post("/api/v1/staff-operations/waste-events", cookies=headers,
        json={**body, "quantity": "3"})
    assert mismatch.status_code == 409

    damage = client.post("/api/v1/staff-operations/waste-events", cookies=headers,
        json={**body, "movement_type": "DAMAGE", "idempotency_key": str(uuid4()),
            "reason_code": "DAMAGE_STORAGE"})
    assert damage.status_code == 201, damage.text
    for quantity in ("0", "-1"):
        rejected = client.post("/api/v1/staff-operations/waste-events", cookies=headers,
            json={**body, "idempotency_key": str(uuid4()), "quantity": quantity})
        assert rejected.status_code == 422
    wrong_unit = client.post("/api/v1/staff-operations/waste-events", cookies=headers,
        json={**body, "idempotency_key": str(uuid4()), "unit": "kg"})
    assert wrong_unit.status_code == 422
    wrong_branch = client.post("/api/v1/staff-operations/waste-events", cookies=headers,
        json={**body, "idempotency_key": str(uuid4()),
            "branch_id": str(ctx["other_branch"])})
    assert wrong_branch.status_code == 404
    menu = client.post("/api/v1/staff-operations/waste-events", cookies=headers,
        json={**body, "idempotency_key": str(uuid4()),
            "ingredient_product_id": str(ctx["menu"])})
    assert menu.status_code == 422
    cross_company = client.post("/api/v1/staff-operations/waste-events", cookies=headers,
        json={**body, "idempotency_key": str(uuid4()),
            "ingredient_product_id": str(foreign["ingredient"])})
    assert cross_company.status_code == 404
    assert client.get("/api/v1/stock-movements",
        cookies={"stockpilot_session": ctx["staff_token"]}).status_code == 403
    assert client.post(f"/api/v1/stock-movements/{event['id']}/void",
        cookies=headers, json={"reason": "not allowed"}).status_code == 403
    events = client.get("/api/v1/staff-operations/waste-events",
        cookies=headers, params={"start_date": "2026-11-25", "end_date": "2026-11-25"})
    assert events.status_code == 200 and events.json()["total"] == 2
    assert client.get(f"/api/v1/staff-operations/waste-events/{event['id']}",
        cookies=headers).status_code == 200
    analytics = client.get("/api/v1/analytics/waste/overview",
        cookies={"stockpilot_session": ctx["owner_token"]},
        params={"start_date": "2026-11-25", "end_date": "2026-11-25"})
    assert analytics.status_code == 200, analytics.text
    waste_row = next(item for item in analytics.json()["wasted_by_product"]
        if item["product_id"] == str(ctx["ingredient"]))
    assert waste_row["wasted"] == "2.5000"


def test_staff_receipt_confirmation_is_current_line_auditable_and_does_not_duplicate_movements(test_environment):
    client, sessions = test_environment
    ctx = setup_staff_operations(client, sessions, "r")
    headers = {"stockpilot_session": ctx["staff_token"]}
    candidates = client.get("/api/v1/staff-operations/receipts/confirmable",
        cookies=headers)
    assert candidates.status_code == 200, candidates.text
    assert candidates.json()["total"] == 1
    candidate = candidates.json()["items"][0]
    assert candidate["receipt_identity_id"] == str(ctx["identity"])
    assert candidate["quantity_received"] == "5.0000"
    body = {"idempotency_key": str(uuid4())}
    url = f"/api/v1/staff-operations/receipts/{ctx['identity']}/confirm"
    invalid_quantity = client.post(url, cookies=headers,
        json={**body, "quantity_confirmed": "3"})
    assert invalid_quantity.status_code == 422
    confirmed = client.post(url, cookies=headers, json=body)
    assert confirmed.status_code == 201, confirmed.text
    original_id = confirmed.json()["id"]
    assert confirmed.json()["quantity_confirmed"] == "5.0000"
    retry = client.post(url, cookies=headers, json=body)
    assert retry.status_code == 200 and retry.json()["id"] == original_id
    assert client.post(url, cookies=headers, json={"idempotency_key": str(uuid4())}).json()["id"] == original_id
    assert client.get("/api/v1/staff-operations/receipts/confirmable",
        cookies=headers).json()["total"] == 0

    with sessions() as db:
        old_line = db.get(PurchaseLine, ctx["purchase_line"])
        old_upload = db.get(DailyUpload, ctx["upload"])
        old_upload.is_current = False
        replacement_upload = DailyUpload(company_id=ctx["company_id"],
            branch_id=ctx["branch"], business_date=old_upload.business_date,
            uploaded_by_membership_id=old_upload.uploaded_by_membership_id,
            object_key=f"test/{uuid4()}", original_filename="corrected.xlsx",
            content_type=XLSX, file_size_bytes=100, version=2, status="UPLOADED",
            is_current=True, processing_status="COMPLETED")
        db.add(replacement_upload); db.flush()
        replacement = PurchaseLine(company_id=ctx["company_id"], branch_id=ctx["branch"],
            source_upload_id=replacement_upload.id, product_id=old_line.product_id,
            receipt_id=old_line.receipt_id, receipt_line_id=old_line.receipt_line_id,
            business_date=old_line.business_date, receipt_date=old_line.receipt_date,
            supplier_name=old_line.supplier_name, quantity_received=Decimal("4"),
            unit_purchase_price=old_line.unit_purchase_price, purchase_unit="g",
            batch_number=old_line.batch_number, receipt_identity_id=old_line.receipt_identity_id)
        db.add(replacement); db.flush()
        current = db.get(PurchaseReceiptCurrentLine, ctx["identity"])
        current.purchase_line_id = replacement.id
        db.add(StockMovement(company_id=ctx["company_id"], branch_id=ctx["branch"],
            ingredient_product_id=old_line.product_id, movement_date=replacement.receipt_date,
            movement_type="PURCHASE_RECEIPT", quantity=replacement.quantity_received,
            unit="g", batch_number=replacement.batch_number,
            source_upload_id=replacement_upload.id, purchase_line_id=replacement.id,
            origin_type="UPLOAD", physical_event_id=ctx["identity"],
            source_reference=f"EVENT-r", reason_code="RECEIVED_FROM_SUPPLIER"))
        db.commit()
        replacement_line_id = replacement.id
    corrected_confirmation = client.post(url, cookies=headers,
        json={"idempotency_key": str(uuid4())})
    assert corrected_confirmation.status_code == 201, corrected_confirmation.text
    assert corrected_confirmation.json()["purchase_line_id"] == str(replacement_line_id)
    history = client.get("/api/v1/staff-operations/receipt-confirmations", cookies=headers)
    assert history.status_code == 200 and history.json()["total"] == 2
    assert client.get("/api/v1/staff-operations/receipt-confirmations",
        cookies={"stockpilot_session": ctx["owner_token"]}).json()["total"] == 2
    assert client.get(f"/api/v1/staff-operations/receipt-confirmations/{original_id}",
        cookies=headers).status_code == 200
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(PurchaseReceiptConfirmation)) == 2
        # The two upload versions provide two retained source movements; the
        # confirmation requests themselves added no further receipt movements.
        assert db.scalar(select(func.count()).select_from(StockMovement).where(
            StockMovement.movement_type == "PURCHASE_RECEIPT")) == 2


def test_receipt_and_count_scope_blocks_analyst_manager_and_cross_branch(test_environment):
    client, sessions = test_environment
    ctx = setup_staff_operations(client, sessions, "s")
    foreign = setup_staff_operations(client, sessions, "foreign-receipt")
    headers = {"stockpilot_session": ctx["manager_token"]}
    assert client.get("/api/v1/staff-operations/receipts/confirmable",
        cookies=headers).status_code == 403
    assert client.get("/api/v1/staff-operations/stock-counts",
        cookies=headers).status_code == 403
    assert client.post(f"/api/v1/staff-operations/receipts/{ctx['identity']}/confirm",
        cookies=headers, json={"idempotency_key": str(uuid4())}).status_code == 403
    assert client.post(f"/api/v1/staff-operations/receipts/{foreign['identity']}/confirm",
        cookies={"stockpilot_session": ctx["staff_token"]},
        json={"idempotency_key": str(uuid4())}).status_code == 404
    assert client.get("/api/v1/staff-operations/receipts/confirmable",
        cookies={"stockpilot_session": ctx["analyst_token"]}).status_code == 403
    assert client.post("/api/v1/staff-operations/waste-events",
        cookies={"stockpilot_session": ctx["analyst_token"]}, json={}).status_code == 403
    with sessions() as db:
        count = db.scalar(select(func.count()).select_from(StockCountSubmission))
        confirmations = db.scalar(select(func.count()).select_from(PurchaseReceiptConfirmation))
        assert count == 0 and confirmations == 0


def test_staff_operational_workflows_reject_an_assigned_branch_after_deactivation(test_environment):
    client, sessions = test_environment
    ctx = setup_staff_operations(client, sessions, "inactive")
    with sessions() as db:
        branch = db.get(Branch, ctx["branch"])
        branch.is_active = False
        db.commit()

    headers = {"stockpilot_session": ctx["staff_token"]}
    count_body = {"branch_id": str(ctx["branch"]),
        "counted_at": "2026-11-25T18:00:00+05:30",
        "idempotency_key": str(uuid4()), "lines": [{
            "ingredient_product_id": str(ctx["ingredient"]), "quantity": "1", "unit": "g"}]}
    waste_body = {"branch_id": str(ctx["branch"]),
        "ingredient_product_id": str(ctx["ingredient"]), "movement_type": "WASTE",
        "occurred_at": "2026-11-25T18:00:00+05:30",
        "idempotency_key": str(uuid4()), "quantity": "1", "unit": "g",
        "reason_code": "WASTE_SPOILAGE"}
    assert client.post("/api/v1/staff-operations/stock-counts",
        cookies=headers, json=count_body).status_code == 403
    assert client.post("/api/v1/staff-operations/waste-events",
        cookies=headers, json=waste_body).status_code == 403
    assert client.post(f"/api/v1/staff-operations/receipts/{ctx['identity']}/confirm",
        cookies=headers, json={"idempotency_key": str(uuid4())}).status_code == 403
    for path in ("/stock-counts", "/waste-events", "/receipt-confirmations",
                 "/receipts/confirmable"):
        assert client.get(f"/api/v1/staff-operations{path}",
            cookies=headers).status_code == 403

    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(StockCountSubmission)) == 0
        assert db.scalar(select(func.count()).select_from(PurchaseReceiptConfirmation)) == 0
        assert db.scalar(select(func.count()).select_from(StockMovement).where(
            StockMovement.origin_type == "MANUAL")) == 0
