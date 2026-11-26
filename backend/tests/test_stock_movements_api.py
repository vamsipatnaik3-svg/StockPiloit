from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import func, select

from app.core.security import hash_password
from app.models import (Branch, BranchMembership, CompanyMembership,
    Product, StockMovement, StockMovementReasonCode, User)


PASSWORD = "StockPilot_Test_123!"
REASONS = [
    ("OTHER_INFLOW_REASON", "OTHER_INFLOW", "Other stock inflow"),
    ("POSITIVE_COUNT_CORRECTION", "POSITIVE_ADJUSTMENT", "Positive count correction"),
    ("POSITIVE_ADJUSTMENT_OTHER", "POSITIVE_ADJUSTMENT", "Other positive adjustment"),
    ("WASTE_SPOILAGE", "WASTE", "Spoilage"),
    ("WASTE_OTHER", "WASTE", "Other waste"),
    ("STAFF_MEAL", "STAFF_CONSUMPTION", "Staff meal"),
    ("DAMAGE_STORAGE", "DAMAGE", "Storage damage"),
    ("NEGATIVE_COUNT_CORRECTION", "NEGATIVE_ADJUSTMENT", "Negative count correction"),
    ("NEGATIVE_ADJUSTMENT_OTHER", "NEGATIVE_ADJUSTMENT", "Other negative adjustment"),
    ("OTHER_OUTFLOW_REASON", "OTHER_OUTFLOW", "Other stock outflow"),
]


def register(client, email, company_name):
    response = client.post("/api/v1/auth/register", json={
        "full_name": "Movement Owner", "email": email,
        "password": PASSWORD, "company_name": company_name,
        "industry": "grocery", "country_code": "IN", "currency": "INR",
        "timezone": "Asia/Kolkata",
    })
    assert response.status_code == 201, response.text
    login = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return login.cookies.get("stockpilot_session")


def create_branch(client, token, name, code):
    response = client.post("/api/v1/branches", cookies={"stockpilot_session": token}, json={
        "name": name, "code": code, "country_code": "IN", "timezone": "Asia/Kolkata",
    })
    assert response.status_code == 201, response.text
    return response.json()["id"]


def create_role_client(client, sessions, company_id, role, email, branch_ids=()):
    with sessions() as db:
        user = User(full_name=role.title(), email=email,
            password_hash=hash_password(PASSWORD), is_active=True)
        db.add(user)
        db.flush()
        membership = CompanyMembership(company_id=company_id, user_id=user.id, role=role)
        db.add(membership)
        db.flush()
        for branch_id in branch_ids:
            db.add(BranchMembership(branch_id=UUID(branch_id), company_membership_id=membership.id))
        db.commit()
    login = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return login.cookies.get("stockpilot_session"), user.id


def setup_company(client, sessions, email="movements@example.com", name="Movement Company"):
    owner_token = register(client, email, name)
    branch_a = create_branch(client, owner_token, "Main", "BR-001")
    branch_b = create_branch(client, owner_token, "Second", "BR-002")
    ingredient = client.post("/api/v1/products", cookies={"stockpilot_session": owner_token}, json={
        "sku": "ING-001", "product_name": "Coffee beans", "unit_of_measure": "g",
        "product_kind": "INGREDIENT",
    }).json()
    menu = client.post("/api/v1/products", cookies={"stockpilot_session": owner_token}, json={
        "sku": "MENU-001", "product_name": "Cappuccino", "unit_of_measure": "pcs",
        "product_kind": "MENU_ITEM",
    }).json()
    legacy = client.post("/api/v1/products", cookies={"stockpilot_session": owner_token}, json={
        "sku": "LEGACY-001", "product_name": "Old product", "unit_of_measure": "EA",
    }).json()
    with sessions() as db:
        membership = db.scalar(select(CompanyMembership).join(User).where(User.email == email))
        company_id = membership.company_id
        for code, kind, label in REASONS:
            if db.get(StockMovementReasonCode, (code, kind)) is None:
                db.add(StockMovementReasonCode(code=code, movement_type=kind, label=label))
        db.commit()
    return {"token": owner_token, "company_id": company_id, "branch_a": branch_a,
        "branch_b": branch_b, "ingredient": ingredient, "menu": menu,
        "legacy": legacy, "owner_email": email}


def payload(branch_id, ingredient_id, **overrides):
    value = {
        "branch_id": branch_id,
        "ingredient_product_id": ingredient_id,
        "movement_type": "WASTE",
        "movement_date": "2026-11-25",
        "quantity": "12.5000",
        "unit": "g",
        "reason_code": "WASTE_SPOILAGE",
    }
    value.update(overrides)
    return value


def create_movement(client, token, body):
    return client.post("/api/v1/stock-movements", cookies={"stockpilot_session": token}, json=body)


def test_owner_creates_inflow_and_outflow_lists_details_and_soft_voids(test_environment):
    client, sessions = test_environment
    ctx = setup_company(client, sessions)
    inflow = create_movement(client, ctx["token"], payload(ctx["branch_b"], ctx["ingredient"]["id"],
        movement_type="OTHER_INFLOW", reason_code="OTHER_INFLOW_REASON",
        reason_detail="Opening sample delivery", quantity="2.1250", source_reference="NOTE-17",
        batch_number="LOT-17"))
    assert inflow.status_code == 201, inflow.text
    assert inflow.json()["direction"] == "INFLOW"
    assert inflow.json()["origin_type"] == "MANUAL"
    assert inflow.json()["source_upload_id"] is None
    assert inflow.json()["purchase_line_id"] is None
    assert inflow.json()["transfer_id"] is None
    assert inflow.json()["created_by_user_id"]
    assert inflow.json()["quantity"] == "2.1250"

    outflow = create_movement(client, ctx["token"], payload(ctx["branch_a"], ctx["ingredient"]["id"]))
    assert outflow.status_code == 201, outflow.text
    assert outflow.json()["direction"] == "OUTFLOW"

    detail = client.get(f"/api/v1/stock-movements/{outflow.json()['id']}",
        cookies={"stockpilot_session": ctx["token"]})
    assert detail.status_code == 200
    assert detail.json()["ingredient_sku"] == "ING-001"
    assert detail.json()["reason_label"] == "Spoilage"

    voided = client.post(f"/api/v1/stock-movements/{outflow.json()['id']}/void",
        cookies={"stockpilot_session": ctx["token"]}, json={"reason": "Counted twice"})
    assert voided.status_code == 200, voided.text
    assert voided.json()["void_reason"] == "Counted twice"
    assert voided.json()["voided_by_user_id"] == outflow.json()["created_by_user_id"]
    original_voided_at = voided.json()["voided_at"]

    repeated = client.post(f"/api/v1/stock-movements/{outflow.json()['id']}/void",
        cookies={"stockpilot_session": ctx["token"]}, json={"reason": "Overwrite attempt"})
    assert repeated.status_code == 409
    assert repeated.json()["detail"] == "Stock movement is already voided."
    with sessions() as db:
        stored = db.get(StockMovement, UUID(outflow.json()["id"]))
        assert stored.void_reason == "Counted twice"
        assert stored.voided_at.isoformat().replace("+00:00", "") == original_voided_at.replace("Z", "")
        assert db.scalar(select(func.count()).select_from(StockMovement)) == 2

    active = client.get("/api/v1/stock-movements?state=ACTIVE&limit=1&offset=0",
        cookies={"stockpilot_session": ctx["token"]})
    voided_list = client.get("/api/v1/stock-movements?state=VOIDED",
        cookies={"stockpilot_session": ctx["token"]})
    all_items = client.get("/api/v1/stock-movements?state=ALL&branch_id=" + ctx["branch_b"],
        cookies={"stockpilot_session": ctx["token"]})
    filtered = client.get("/api/v1/stock-movements?state=ACTIVE&branch_id=" + ctx["branch_b"]
        + "&ingredient_product_id=" + ctx["ingredient"]["id"]
        + "&movement_type=OTHER_INFLOW&start_date=2026-11-25&end_date=2026-11-25&batch_number=LOT-17",
        cookies={"stockpilot_session": ctx["token"]})
    assert active.json()["total"] == 1 and len(active.json()["items"]) == 1
    assert voided_list.json()["total"] == 1
    assert all_items.json()["total"] == 1
    assert filtered.json()["total"] == 1
    assert active.json()["items"][0]["movement_type"] == "OTHER_INFLOW"


def test_manual_movement_validates_kind_unit_reason_and_server_controlled_fields(test_environment):
    client, _sessions = test_environment
    ctx = setup_company(client, _sessions)
    inactive = client.post("/api/v1/products", cookies={"stockpilot_session": ctx["token"]}, json={
        "sku": "ING-INACTIVE", "product_name": "Inactive beans", "unit_of_measure": "g",
        "product_kind": "INGREDIENT",
    }).json()
    assert client.patch(f"/api/v1/products/{inactive['id']}",
        cookies={"stockpilot_session": ctx["token"]}, json={"is_active": False}).status_code == 200
    cases = [
        (payload(ctx["branch_a"], ctx["menu"]["id"]), 422),
        (payload(ctx["branch_a"], ctx["legacy"]["id"], unit="EA"), 422),
        (payload(ctx["branch_a"], inactive["id"]), 422),
        (payload(ctx["branch_a"], ctx["ingredient"]["id"], unit="kg"), 422),
        (payload(ctx["branch_a"], ctx["ingredient"]["id"], reason_code="DAMAGE_STORAGE"), 422),
        (payload(ctx["branch_a"], ctx["ingredient"]["id"], movement_type="PURCHASE_RECEIPT",
            reason_code="RECEIVED_FROM_SUPPLIER"), 422),
        (payload(ctx["branch_a"], ctx["ingredient"]["id"], movement_type="TRANSFER_IN",
            reason_code="TRANSFER_IN_REASON"), 422),
        (payload(ctx["branch_a"], ctx["ingredient"]["id"], movement_type="TRANSFER_OUT",
            reason_code="TRANSFER_OUT_REASON"), 422),
        (payload(ctx["branch_a"], ctx["ingredient"]["id"], movement_type="UNCLASSIFIED"), 422),
        (payload(ctx["branch_a"], ctx["ingredient"]["id"], quantity="0"), 422),
        (payload(ctx["branch_a"], ctx["ingredient"]["id"], quantity="-1"), 422),
        (payload(ctx["branch_a"], ctx["ingredient"]["id"], movement_date="not-a-date"), 422),
        (payload(ctx["branch_a"], ctx["ingredient"]["id"], movement_type="NEGATIVE_ADJUSTMENT",
            reason_code="NEGATIVE_COUNT_CORRECTION"), 422),
        (payload(ctx["branch_a"], ctx["ingredient"]["id"], company_id=str(ctx["company_id"])), 422),
        (payload(ctx["branch_a"], ctx["ingredient"]["id"], created_by_user_id="00000000-0000-0000-0000-000000000000"), 422),
        (payload(ctx["branch_a"], ctx["ingredient"]["id"], origin_type="UPLOAD"), 422),
        (payload(ctx["branch_a"], ctx["ingredient"]["id"], transfer_id="00000000-0000-0000-0000-000000000000"), 422),
        (payload(ctx["branch_a"], ctx["ingredient"]["id"], purchase_line_id="00000000-0000-0000-0000-000000000000"), 422),
    ]
    for body, expected_status in cases:
        response = create_movement(client, ctx["token"], body)
        assert response.status_code == expected_status, (body, response.text)

    for movement_type, reason_code in [
        ("POSITIVE_ADJUSTMENT", "POSITIVE_COUNT_CORRECTION"),
        ("NEGATIVE_ADJUSTMENT", "NEGATIVE_COUNT_CORRECTION"),
    ]:
        missing_detail = create_movement(client, ctx["token"], payload(ctx["branch_a"],
            ctx["ingredient"]["id"], movement_type=movement_type, reason_code=reason_code))
        assert missing_detail.status_code == 422
        valid = create_movement(client, ctx["token"], payload(ctx["branch_a"],
            ctx["ingredient"]["id"], movement_type=movement_type, reason_code=reason_code,
            reason_detail="Physical stock count correction"))
        assert valid.status_code == 201, valid.text

    missing_other_detail = create_movement(client, ctx["token"], payload(ctx["branch_a"],
        ctx["ingredient"]["id"], movement_type="OTHER_INFLOW",
        reason_code="OTHER_INFLOW_REASON"))
    assert missing_other_detail.status_code == 422


def test_manager_branch_scope_and_staff_analyst_write_denial(test_environment):
    client, sessions = test_environment
    ctx = setup_company(client, sessions)
    manager_token, manager_user_id = create_role_client(client, sessions, ctx["company_id"],
        "MANAGER", "movement-manager@example.com", [ctx["branch_a"]])
    assigned = create_movement(client, manager_token,
        payload(ctx["branch_a"], ctx["ingredient"]["id"]))
    assert assigned.status_code == 201, assigned.text
    assert assigned.json()["created_by_user_id"] == str(manager_user_id)

    unassigned = create_movement(client, manager_token,
        payload(ctx["branch_b"], ctx["ingredient"]["id"]))
    assert unassigned.status_code == 403
    assert client.get("/api/v1/stock-movements?branch_id=" + ctx["branch_b"],
        cookies={"stockpilot_session": manager_token}).status_code == 403
    assert client.get(f"/api/v1/stock-movements/{assigned.json()['id']}",
        cookies={"stockpilot_session": manager_token}).status_code == 200
    assert client.post(f"/api/v1/stock-movements/{assigned.json()['id']}/void",
        cookies={"stockpilot_session": manager_token}, json={"reason": "Allowed branch"}).status_code == 200

    for role in ("STAFF", "ANALYST"):
        token, _ = create_role_client(client, sessions, ctx["company_id"], role,
            f"movement-{role.lower()}@example.com", [ctx["branch_a"]])
        assert create_movement(client, token, payload(ctx["branch_a"],
            ctx["ingredient"]["id"])).status_code == 403
        assert client.post(f"/api/v1/stock-movements/{assigned.json()['id']}/void",
            cookies={"stockpilot_session": token}, json={"reason": "Not allowed"}).status_code == 403
        assert client.get("/api/v1/stock-movements",
            cookies={"stockpilot_session": token}).status_code == 403


def test_cross_company_branch_product_and_movement_isolation(test_environment):
    client, sessions = test_environment
    first = setup_company(client, sessions)
    second = setup_company(client, sessions, email="other-movements@example.com", name="Other Company")
    own_movement = create_movement(client, first["token"], payload(first["branch_a"], first["ingredient"]["id"]))
    assert own_movement.status_code == 201

    cross_branch = create_movement(client, first["token"], payload(second["branch_a"], first["ingredient"]["id"]))
    cross_product = create_movement(client, first["token"], payload(first["branch_a"], second["ingredient"]["id"]))
    assert cross_branch.status_code == 404
    assert cross_product.status_code == 404
    assert client.get("/api/v1/stock-movements?branch_id=" + second["branch_a"],
        cookies={"stockpilot_session": first["token"]}).status_code == 404

    other_view = client.get("/api/v1/stock-movements", cookies={"stockpilot_session": second["token"]})
    assert other_view.status_code == 200
    assert other_view.json()["total"] == 0
    for path in (f"/api/v1/stock-movements/{own_movement.json()['id']}",
                 f"/api/v1/stock-movements/{own_movement.json()['id']}/void"):
        if path.endswith("/void"):
            response = client.post(path, cookies={"stockpilot_session": second["token"]},
                json={"reason": "Cross-tenant attempt"})
        else:
            response = client.get(path, cookies={"stockpilot_session": second["token"]})
        assert response.status_code == 404


def test_manager_cannot_void_other_branch_or_upload_origin_movements(test_environment):
    client, sessions = test_environment
    ctx = setup_company(client, sessions)
    owner_movement = create_movement(client, ctx["token"],
        payload(ctx["branch_b"], ctx["ingredient"]["id"]))
    manager_token, _ = create_role_client(client, sessions, ctx["company_id"],
        "MANAGER", "movement-manager-void@example.com", [ctx["branch_a"]])
    denied = client.post(f"/api/v1/stock-movements/{owner_movement.json()['id']}/void",
        cookies={"stockpilot_session": manager_token}, json={"reason": "Outside branch"})
    assert denied.status_code == 403
    assert client.get(f"/api/v1/stock-movements/{owner_movement.json()['id']}",
        cookies={"stockpilot_session": manager_token}).status_code == 403

    with sessions() as db:
        membership = db.scalar(select(CompanyMembership).join(User).where(
            User.email == ctx["owner_email"]))
        uploaded = StockMovement(company_id=ctx["company_id"], branch_id=UUID(ctx["branch_a"]),
            ingredient_product_id=UUID(ctx["ingredient"]["id"]), movement_date=date(2026, 11, 25),
            movement_type="WASTE", quantity=Decimal("1"), unit="g", origin_type="UPLOAD",
            source_upload_id=UUID("00000000-0000-0000-0000-000000000001"),
            physical_event_id=UUID("00000000-0000-0000-0000-000000000002"),
            reason_code="WASTE_SPOILAGE")
        db.add(uploaded)
        db.commit()
        uploaded_id = uploaded.id

    rejected = client.post(f"/api/v1/stock-movements/{uploaded_id}/void",
        cookies={"stockpilot_session": ctx["token"]}, json={"reason": "Must remain upload evidence"})
    assert rejected.status_code == 409
    with sessions() as db:
        retained = db.get(StockMovement, uploaded_id)
        assert retained.voided_at is None
        assert retained.voided_by_user_id is None
