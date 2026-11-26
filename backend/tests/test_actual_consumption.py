from datetime import date
import copy
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.core.branch_scope import BranchAccessScope, resolve_branch_scope
from app.models import (Branch, CompanyMembership, DailyUpload, InventorySnapshot,
    ModifierGroup, ModifierOption, ModifierRecipeIngredient, Product, PurchaseLine,
    BranchMembership, PurchaseReceiptCurrentLine, PurchaseReceiptIdentity, RecipeIngredient,
    RecipeVersion, SalesRecord, StockCoverageDeclaration, StockMovement,
    StockMovementReasonCode, StockTransfer, User)
from app.services.actual_consumption import calculate_actual_consumption
from app.services.actual_consumption_queries import load_actual_consumption_inputs
from app.services.theoretical_consumption import calculate_theoretical_consumption


PASSWORD = "StockPilot_Test_123!"
DAY1 = date(2026, 11, 25)
DAY2 = date(2026, 11, 26)
TYPES = (
    "PURCHASE_RECEIPT", "OTHER_INFLOW", "POSITIVE_ADJUSTMENT", "TRANSFER_IN",
    "WASTE", "STAFF_CONSUMPTION", "DAMAGE", "NEGATIVE_ADJUSTMENT",
    "OTHER_OUTFLOW", "TRANSFER_OUT",
)
REASONS = {
    "PURCHASE_RECEIPT": "RECEIVED_FROM_SUPPLIER",
    "OTHER_INFLOW": "OTHER_INFLOW_REASON",
    "POSITIVE_ADJUSTMENT": "POSITIVE_COUNT_CORRECTION",
    "TRANSFER_IN": "TRANSFER_IN_REASON",
    "WASTE": "WASTE_SPOILAGE",
    "STAFF_CONSUMPTION": "STAFF_MEAL",
    "DAMAGE": "DAMAGE_STORAGE",
    "NEGATIVE_ADJUSTMENT": "NEGATIVE_COUNT_CORRECTION",
    "OTHER_OUTFLOW": "OTHER_OUTFLOW_REASON",
    "TRANSFER_OUT": "TRANSFER_OUT_REASON",
}


def setup_company(client, sessions, *, email="actual@example.com", branches=1):
    response = client.post("/api/v1/auth/register", json={
        "full_name": "Actual Owner", "email": email, "password": PASSWORD,
        "company_name": "Actual Cafe", "industry": "CAFE", "country_code": "IN",
        "currency": "INR", "timezone": "Asia/Kolkata",
    })
    assert response.status_code == 201, response.text
    company_id = UUID(response.json()["company_id"])
    login = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200
    token = login.cookies.get("stockpilot_session")
    with sessions() as db:
        membership = db.scalar(select(CompanyMembership).join(User).where(User.email == email))
        branch_rows = [Branch(company_id=company_id, name=f"Cafe {index + 1}",
            code=f"C{index + 1:02}", country_code="IN", timezone="Asia/Kolkata")
            for index in range(branches)]
        ingredient = Product(company_id=company_id, sku="ING-COFFEE",
            product_name="Coffee beans", unit_of_measure="g", product_kind="INGREDIENT")
        menu = Product(company_id=company_id, sku="MENU-COFFEE",
            product_name="Coffee", unit_of_measure="pcs", product_kind="MENU_ITEM")
        db.add_all([*branch_rows, ingredient, menu])
        db.flush()
        for movement_type, code in REASONS.items():
            if db.get(StockMovementReasonCode, (code, movement_type)) is None:
                db.add(StockMovementReasonCode(code=code, movement_type=movement_type,
                    label=code.replace("_", " ").title()))
        # Adjustments have a second reason in some fixture databases; one is enough.
        db.commit()
        return {"token": token, "company_id": company_id,
            "membership_id": membership.id, "user_id": membership.user_id,
            "branches": [row.id for row in branch_rows],
            "ingredient_id": ingredient.id, "menu_id": menu.id}


def add_upload(db, ctx, branch_id, day, *, version=1, current=True,
               processing_status="COMPLETED"):
    upload = DailyUpload(company_id=ctx["company_id"], branch_id=branch_id,
        business_date=day, uploaded_by_membership_id=ctx["membership_id"],
        object_key=f"actual/{uuid4()}", original_filename="actual-v3.xlsx",
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        file_size_bytes=128, version=version, status="UPLOADED", is_current=current,
        processing_status=processing_status)
    db.add(upload)
    db.flush()
    return upload


def add_snapshot(db, ctx, upload, *, opening="100", closing="100", batch=""):
    row = InventorySnapshot(company_id=ctx["company_id"], branch_id=upload.branch_id,
        source_upload_id=upload.id, product_id=ctx["ingredient_id"],
        business_date=upload.business_date, batch_number=batch,
        opening_quantity=Decimal(str(opening)), closing_quantity=Decimal(str(closing)),
        unit="g", expiry_date=None, unit_cost=None, damaged_quantity=Decimal(0),
        wasted_quantity=Decimal(0), staff_consumption_quantity=None,
        adjustment_quantity=Decimal(0), adjustment_reason=None)
    db.add(row)
    db.flush()
    return row


def add_coverage(db, ctx, upload, *, states=None, snapshots=True,
                 boundary_status="COMPLETE", ingredient_status=None,
                 batch_status=None, omit=()):
    states = states or {}
    any_snapshot = snapshots
    zero_status = "COMPLETE" if any_snapshot else "NO_STOCK"
    coverage = [
        ("INGREDIENT", "INGREDIENT", ingredient_status or zero_status, None),
        ("BATCH", "ALL_BATCHES", batch_status or zero_status, None),
        ("OPENING_STOCK", "INGREDIENT", boundary_status, None),
        ("CLOSING_STOCK", "INGREDIENT", boundary_status, None),
    ]
    for movement_type in TYPES:
        coverage.append(("MOVEMENT_CATEGORY", "INGREDIENT",
            states.get(movement_type, "NOT_APPLICABLE"), movement_type))
    for dimension, scope, status, movement_type in coverage:
        if (dimension, movement_type) in omit:
            continue
        db.add(StockCoverageDeclaration(company_id=ctx["company_id"],
            branch_id=upload.branch_id, business_date=upload.business_date,
            source_upload_id=upload.id, ingredient_product_id=ctx["ingredient_id"],
            unit="g", coverage_dimension=dimension, scope_type=scope,
            batch_number=None, movement_type=movement_type, status=status,
            inventory_snapshot_id=None))


def add_movement(db, ctx, branch_id, kind, quantity, *, day=DAY1,
                 upload=None, purchase_line=None, transfer_id=None,
                 voided=False, unit="g", batch=None):
    movement = StockMovement(company_id=ctx["company_id"], branch_id=branch_id,
        ingredient_product_id=ctx["ingredient_id"], movement_date=day,
        movement_type=kind, quantity=Decimal(str(quantity)), unit=unit,
        batch_number=batch, source_upload_id=upload.id if upload else None,
        purchase_line_id=purchase_line.id if purchase_line else None,
        transfer_id=transfer_id, origin_type="UPLOAD" if upload else "MANUAL",
        physical_event_id=uuid4(), source_reference=None,
        reason_code=REASONS[kind], reason_detail=None,
        created_by_user_id=None if upload else ctx["user_id"],
        voided_by_user_id=ctx["user_id"] if voided else None,
        voided_at=__import__("datetime").datetime.now().astimezone() if voided else None,
        void_reason="test void" if voided else None)
    db.add(movement)
    db.flush()
    return movement


def add_purchase_with_movement(db, ctx, upload, quantity="10", *, receipt_date=DAY1,
                               unit="g", batch=None, include_movement=True):
    identity = PurchaseReceiptIdentity(company_id=ctx["company_id"],
        branch_id=upload.branch_id, receipt_event_id=f"EVENT-{uuid4()}")
    db.add(identity)
    db.flush()
    line = PurchaseLine(company_id=ctx["company_id"], branch_id=upload.branch_id,
        source_upload_id=upload.id, product_id=ctx["ingredient_id"],
        receipt_id="INV-1", receipt_line_id="LINE-1", business_date=upload.business_date,
        receipt_date=receipt_date, supplier_name="Supplier",
        quantity_received=Decimal(str(quantity)), unit_purchase_price=Decimal("1"),
        purchase_unit=unit, batch_number=batch, expiry_date=None,
        receipt_identity_id=identity.id)
    db.add(line)
    db.flush()
    db.add(PurchaseReceiptCurrentLine(receipt_identity_id=identity.id,
        company_id=ctx["company_id"], branch_id=upload.branch_id,
        purchase_line_id=line.id))
    if include_movement:
        add_movement(db, ctx, upload.branch_id, "PURCHASE_RECEIPT", quantity,
            day=receipt_date, upload=upload, purchase_line=line, batch=batch)
    return line


def add_theory(db, ctx, upload, *, sales_quantity="5", recipe_quantity="6",
               missing_recipe=False, ingredient_id=None):
    recipe = RecipeVersion(company_id=ctx["company_id"], menu_product_id=ctx["menu_id"],
        version=1, effective_from=upload.business_date)
    db.add(recipe)
    db.flush()
    db.add(RecipeIngredient(recipe_version_id=recipe.id,
        ingredient_product_id=ingredient_id or ctx["ingredient_id"],
        quantity=Decimal(str(recipe_quantity)), unit="g"))
    sale = SalesRecord(company_id=ctx["company_id"], branch_id=upload.branch_id,
        source_upload_id=upload.id, product_id=ctx["menu_id"],
        recipe_version_id=None if missing_recipe else recipe.id,
        business_date=upload.business_date, granularity="AGGREGATED",
        aggregate_id=f"AGG-{uuid4()}", source_identity=f"ACTUAL-{uuid4()}",
        transaction_id=None, line_id=None, transaction_at=None,
        quantity=Decimal(str(sales_quantity)), unit_price=Decimal("10"),
        discount_amount=Decimal(0), tax_amount=Decimal(0), net_amount=Decimal("50"),
        sales_channel="IN_STORE")
    db.add(sale)
    return recipe


def request_actual(client, token, query="start_date=2026-11-25&end_date=2026-11-25"):
    return client.get("/api/v1/analytics/ingredient-consumption/actual?" + query,
        cookies={"stockpilot_session": token})


def test_complete_actual_consumption_purchase_once_decimal_and_theoretical_variance(test_environment):
    client, sessions = test_environment
    ctx = setup_company(client, sessions)
    branch = ctx["branches"][0]
    with sessions() as db:
        upload = add_upload(db, ctx, branch, DAY1)
        add_snapshot(db, ctx, upload, opening="100", closing="80")
        add_purchase_with_movement(db, ctx, upload, "10")
        add_movement(db, ctx, branch, "OTHER_INFLOW", "5", upload=upload)
        add_movement(db, ctx, branch, "POSITIVE_ADJUSTMENT", "2", upload=upload)
        for kind, amount in (("WASTE", "2"), ("STAFF_CONSUMPTION", "1"),
                ("DAMAGE", "1"), ("NEGATIVE_ADJUSTMENT", "1"),
                ("OTHER_OUTFLOW", "1")):
            add_movement(db, ctx, branch, kind, amount, upload=upload)
        add_coverage(db, ctx, upload, states={
            "PURCHASE_RECEIPT": "COMPLETE", "OTHER_INFLOW": "COMPLETE",
            "POSITIVE_ADJUSTMENT": "COMPLETE", "WASTE": "COMPLETE",
            "STAFF_CONSUMPTION": "COMPLETE", "DAMAGE": "COMPLETE",
            "NEGATIVE_ADJUSTMENT": "COMPLETE", "OTHER_OUTFLOW": "COMPLETE",
        })
        add_theory(db, ctx, upload, sales_quantity="5", recipe_quantity="6")
        db.commit()
    response = request_actual(client, ctx["token"])
    assert response.status_code == 200, response.text
    row = next(row for row in response.json()["items"]
        if row["ingredient_id"] == str(ctx["ingredient_id"]))
    assert row["status"] == "COMPLETE"
    assert Decimal(row["opening_stock"]) == 100
    assert Decimal(row["closing_stock"]) == 80
    assert Decimal(row["total_inflows"]) == 17  # line is counted through its receipt movement once
    assert Decimal(row["total_outflows"]) == 6
    assert Decimal(row["actual_stock_depletion"]) == 37
    assert Decimal(row["known_non_sales_outflows"]) == 6
    assert Decimal(row["actual_sales_related_consumption"]) == 31
    assert Decimal(row["theoretical_consumption"]) == 30
    assert Decimal(row["absolute_variance"]) == 1
    assert Decimal(row["variance_percent"]) == Decimal(100) / Decimal(30)


@pytest.mark.parametrize("state", ["UNREPORTED", "PARTIAL"])
def test_unreported_and_partial_categories_do_not_become_zero(test_environment, state):
    client, sessions = test_environment
    ctx = setup_company(client, sessions, email=f"{state.lower()}@example.com")
    with sessions() as db:
        upload = add_upload(db, ctx, ctx["branches"][0], DAY1)
        add_snapshot(db, ctx, upload)
        add_coverage(db, ctx, upload, states={"WASTE": state})
        db.commit()
    row = request_actual(client, ctx["token"]).json()["items"][0]
    assert row["status"] == "INCOMPLETE"
    assert row["total_outflows"] is None
    assert row["actual_sales_related_consumption"] is None


def test_partial_all_batch_declaration_blocks_ingredient_aggregation(test_environment):
    client, sessions = test_environment
    ctx = setup_company(client, sessions)
    with sessions() as db:
        upload = add_upload(db, ctx, ctx["branches"][0], DAY1)
        add_snapshot(db, ctx, upload, batch="LOT-A")
        add_coverage(db, ctx, upload, batch_status="PARTIAL")
        db.commit()
    row = request_actual(client, ctx["token"]).json()["items"][0]
    assert row["status"] == "INCOMPLETE"
    assert row["actual_stock_depletion"] is None
    assert "BATCH_COVERAGE_PARTIAL" in row["reason_codes"]


def test_historical_v1_v2_without_coverage_are_unknown(test_environment):
    client, sessions = test_environment
    ctx = setup_company(client, sessions)
    with sessions() as db:
        upload = add_upload(db, ctx, ctx["branches"][0], DAY1)
        add_snapshot(db, ctx, upload)
        db.commit()
    row = request_actual(client, ctx["token"]).json()["items"][0]
    assert row["status"] == "INCOMPLETE"
    assert row["actual_stock_depletion"] is None
    assert any("COVERAGE" in reason for reason in row["reason_codes"])


def test_no_completed_upload_returns_unavailable_not_confirmed_zero(test_environment):
    client, sessions = test_environment
    ctx = setup_company(client, sessions)
    row = request_actual(client, ctx["token"]).json()["items"][0]
    assert row["status"] == "UNAVAILABLE"
    assert row["opening_stock"] is None
    assert row["total_inflows"] is None
    assert row["actual_sales_related_consumption"] is None


def test_explicit_no_stock_is_confirmed_zero_but_zero_theory_has_no_percent(test_environment):
    client, sessions = test_environment
    ctx = setup_company(client, sessions)
    with sessions() as db:
        upload = add_upload(db, ctx, ctx["branches"][0], DAY1)
        other_ingredient = Product(company_id=ctx["company_id"], sku="ING-MILK",
            product_name="Roasting sample", unit_of_measure="g", product_kind="INGREDIENT")
        db.add(other_ingredient)
        db.flush()
        add_coverage(db, ctx, upload, snapshots=False, boundary_status="NO_STOCK")
        add_theory(db, ctx, upload, ingredient_id=other_ingredient.id)
        db.commit()
    response = request_actual(client, ctx["token"])
    row = next(row for row in response.json()["items"]
        if row["ingredient_id"] == str(ctx["ingredient_id"]))
    assert row["status"] == "COMPLETE"
    assert row["opening_stock"] == row["closing_stock"] == "0"
    assert row["actual_sales_related_consumption"] == "0"
    assert row["theoretical_status"] == "COMPLETE"
    assert row["theoretical_consumption"] == "0"
    assert row["absolute_variance"] == "0"
    assert row["variance_percent"] is None


def test_multiday_uses_first_opening_and_final_closing_only(test_environment):
    client, sessions = test_environment
    ctx = setup_company(client, sessions)
    with sessions() as db:
        first = add_upload(db, ctx, ctx["branches"][0], DAY1)
        add_snapshot(db, ctx, first, opening="100", closing="90")
        add_coverage(db, ctx, first)
        second = add_upload(db, ctx, ctx["branches"][0], DAY2)
        add_snapshot(db, ctx, second, opening="80", closing="70")
        add_coverage(db, ctx, second)
        db.commit()
    response = request_actual(client, ctx["token"],
        "start_date=2026-11-25&end_date=2026-11-26")
    row = response.json()["items"][0]
    assert row["status"] == "COMPLETE"
    assert Decimal(row["opening_stock"]) == 100
    assert Decimal(row["closing_stock"]) == 70
    assert Decimal(row["actual_stock_depletion"]) == 30


def test_multiple_batches_aggregate_only_with_complete_all_batch_coverage(test_environment):
    client, sessions = test_environment
    ctx = setup_company(client, sessions)
    with sessions() as db:
        upload = add_upload(db, ctx, ctx["branches"][0], DAY1)
        add_snapshot(db, ctx, upload, opening="10", closing="8", batch="LOT-A")
        add_snapshot(db, ctx, upload, opening="20", closing="15", batch="LOT-B")
        add_coverage(db, ctx, upload, batch_status="COMPLETE")
        db.commit()
    row = request_actual(client, ctx["token"]).json()["items"][0]
    assert row["status"] == "COMPLETE"
    assert Decimal(row["opening_stock"]) == 30
    assert Decimal(row["closing_stock"]) == 23
    assert Decimal(row["actual_stock_depletion"]) == 7


def test_missing_daily_upload_does_not_assume_zero_movements(test_environment):
    client, sessions = test_environment
    ctx = setup_company(client, sessions)
    with sessions() as db:
        upload = add_upload(db, ctx, ctx["branches"][0], DAY1)
        add_snapshot(db, ctx, upload, opening="10", closing="10")
        add_coverage(db, ctx, upload)
        db.commit()
    row = request_actual(client, ctx["token"],
        "start_date=2026-11-25&end_date=2026-11-26").json()["items"][0]
    assert row["status"] == "INCOMPLETE"
    assert row["total_inflows"] is None
    assert row["actual_sales_related_consumption"] is None
    assert "MISSING_OR_DUPLICATE_CURRENT_COMPLETED_UPLOAD" in row["reason_codes"]


def test_missing_closing_snapshot_keeps_dependent_totals_null(test_environment):
    client, sessions = test_environment
    ctx = setup_company(client, sessions)
    with sessions() as db:
        upload = add_upload(db, ctx, ctx["branches"][0], DAY1)
        add_snapshot(db, ctx, upload)
        add_coverage(db, ctx, upload, omit={("CLOSING_STOCK", None)})
        db.commit()
    row = request_actual(client, ctx["token"]).json()["items"][0]
    assert row["status"] == "INCOMPLETE"
    assert Decimal(row["opening_stock"]) == 100
    assert row["closing_stock"] is None
    assert row["actual_stock_depletion"] is None


def test_missing_opening_snapshot_keeps_dependent_totals_null(test_environment):
    client, sessions = test_environment
    ctx = setup_company(client, sessions)
    with sessions() as db:
        upload = add_upload(db, ctx, ctx["branches"][0], DAY1)
        add_snapshot(db, ctx, upload)
        add_coverage(db, ctx, upload, omit={("OPENING_STOCK", None)})
        db.commit()
    row = request_actual(client, ctx["token"]).json()["items"][0]
    assert row["status"] == "INCOMPLETE"
    assert row["opening_stock"] is None
    assert Decimal(row["closing_stock"]) == 100
    assert row["actual_stock_depletion"] is None


def test_missing_purchase_receipt_movement_is_invalid_data(test_environment):
    client, sessions = test_environment
    ctx = setup_company(client, sessions)
    with sessions() as db:
        upload = add_upload(db, ctx, ctx["branches"][0], DAY1)
        add_snapshot(db, ctx, upload, opening="100", closing="100")
        line = add_purchase_with_movement(db, ctx, upload, "10", include_movement=False)
        add_coverage(db, ctx, upload, states={"PURCHASE_RECEIPT": "COMPLETE"})
        db.commit()
    row = request_actual(client, ctx["token"]).json()["items"][0]
    assert row["status"] == "INVALID_DATA"
    assert "MISSING_OR_DUPLICATE_PURCHASE_RECEIPT_MOVEMENT" in row["reason_codes"]
    assert row["actual_stock_depletion"] is None


def test_not_applicable_category_with_movement_is_invalid(test_environment):
    client, sessions = test_environment
    ctx = setup_company(client, sessions)
    with sessions() as db:
        upload = add_upload(db, ctx, ctx["branches"][0], DAY1)
        add_snapshot(db, ctx, upload)
        add_movement(db, ctx, upload.branch_id, "WASTE", "2", upload=upload)
        add_coverage(db, ctx, upload)  # WASTE defaults to NOT_APPLICABLE.
        db.commit()
    row = request_actual(client, ctx["token"]).json()["items"][0]
    assert row["status"] == "INVALID_DATA"
    assert "CONTRADICTORY_NOT_APPLICABLE_MOVEMENT" in row["reason_codes"]


def test_snapshot_waste_reconciles_to_ledger_without_double_counting(test_environment):
    client, sessions = test_environment
    ctx = setup_company(client, sessions)
    with sessions() as db:
        upload = add_upload(db, ctx, ctx["branches"][0], DAY1)
        snapshot = add_snapshot(db, ctx, upload, opening="10", closing="7")
        snapshot.wasted_quantity = Decimal("2")
        add_movement(db, ctx, upload.branch_id, "WASTE", "2", upload=upload)
        add_coverage(db, ctx, upload, states={"WASTE": "COMPLETE"})
        db.commit()
    row = request_actual(client, ctx["token"]).json()["items"][0]
    assert row["status"] == "COMPLETE"
    assert Decimal(row["total_outflows"]) == 2
    assert Decimal(row["actual_stock_depletion"]) == 3
    assert Decimal(row["actual_sales_related_consumption"]) == 1


def test_positive_snapshot_waste_without_ledger_movement_is_invalid(test_environment):
    client, sessions = test_environment
    ctx = setup_company(client, sessions)
    with sessions() as db:
        upload = add_upload(db, ctx, ctx["branches"][0], DAY1)
        snapshot = add_snapshot(db, ctx, upload)
        snapshot.wasted_quantity = Decimal("2")
        add_coverage(db, ctx, upload, states={"WASTE": "COMPLETE"})
        db.commit()
    row = request_actual(client, ctx["token"]).json()["items"][0]
    assert row["status"] == "INVALID_DATA"
    assert "INVENTORY_MOVEMENT_QUANTITY_MISMATCH" in row["reason_codes"]


def test_negative_stock_observation_is_invalid_data(test_environment):
    client, sessions = test_environment
    ctx = setup_company(client, sessions)
    with sessions() as db:
        upload = add_upload(db, ctx, ctx["branches"][0], DAY1)
        add_snapshot(db, ctx, upload, opening="-1", closing="0")
        add_coverage(db, ctx, upload)
        db.commit()
    row = request_actual(client, ctx["token"]).json()["items"][0]
    assert row["status"] == "INVALID_DATA"
    assert "INVALID_STOCK_QUANTITY" in row["reason_codes"]


def test_legacy_purchase_without_unit_is_not_counted_as_inflow(test_environment):
    client, sessions = test_environment
    ctx = setup_company(client, sessions)
    with sessions() as db:
        upload = add_upload(db, ctx, ctx["branches"][0], DAY1)
        add_snapshot(db, ctx, upload, opening="100", closing="100")
        line = add_purchase_with_movement(db, ctx, upload, "10", include_movement=False)
        line.purchase_unit = None
        add_coverage(db, ctx, upload, states={"PURCHASE_RECEIPT": "COMPLETE"})
        db.commit()
    row = request_actual(client, ctx["token"]).json()["items"][0]
    assert row["status"] == "INCOMPLETE"
    assert row["total_inflows"] is None
    assert row["actual_stock_depletion"] is None
    assert "PURCHASE_UNIT_UNKNOWN" in row["reason_codes"]


@pytest.mark.parametrize("duplicate_kind", ["snapshot", "purchase_movement"])
def test_duplicate_stock_or_purchase_receipt_evidence_is_invalid(test_environment, duplicate_kind):
    client, sessions = test_environment
    ctx = setup_company(client, sessions)
    branch = ctx["branches"][0]
    with sessions() as db:
        upload = add_upload(db, ctx, branch, DAY1)
        snapshot = add_snapshot(db, ctx, upload)
        movement = None
        if duplicate_kind == "purchase_movement":
            line = add_purchase_with_movement(db, ctx, upload, "10")
            movement = db.scalar(select(StockMovement).where(
                StockMovement.purchase_line_id == line.id))
        add_coverage(db, ctx, upload, states={"PURCHASE_RECEIPT": "COMPLETE"})
        db.commit()
        branch_scope = BranchAccessScope(ctx["company_id"], ctx["membership_id"],
            "OWNER", frozenset(ctx["branches"]), "COMPANY")
        data = load_actual_consumption_inputs(db, ctx["company_id"], DAY1,
            DAY1, branch_scope, ctx["ingredient_id"])
        if duplicate_kind == "snapshot":
            data["snapshots"] = (*data["snapshots"], copy.copy(snapshot))
        else:
            data["movements"] = (*data["movements"], copy.copy(movement))
        theory = calculate_theoretical_consumption(data["theoretical_scopes"],
            data["theoretical_sales"], ctx["company_id"])
        data["theoretical_scopes"] = theory["scopes"]
        data["theoretical_items"] = theory["items"]
        calculated = calculate_actual_consumption(data, ctx["company_id"],
            DAY1, DAY1, None, ctx["ingredient_id"])
    row = calculated["items"][0]
    assert row["status"] == "INVALID_DATA"
    assert row["actual_sales_related_consumption"] is None
    assert any("DUPLICATE" in reason for reason in row["reason_codes"])


def test_actual_and_theoretical_loaders_apply_manager_scope_before_aggregation(test_environment):
    client, sessions = test_environment
    ctx = setup_company(client, sessions, branches=2)
    with sessions() as db:
        manager_user = User(full_name="Scoped Manager", email="scoped-manager@example.com",
            password_hash="unused", is_active=True)
        db.add(manager_user)
        db.flush()
        manager = CompanyMembership(company_id=ctx["company_id"],
            user_id=manager_user.id, role="MANAGER")
        db.add(manager)
        db.flush()
        db.add(BranchMembership(branch_id=ctx["branches"][0],
            company_membership_id=manager.id))
        shared_recipe = None
        for branch_id in ctx["branches"]:
            upload = add_upload(db, ctx, branch_id, DAY1)
            add_snapshot(db, ctx, upload)
            add_coverage(db, ctx, upload)
            if shared_recipe is None:
                add_theory(db, ctx, upload)
                shared_recipe = db.scalar(select(RecipeVersion).where(
                    RecipeVersion.company_id == ctx["company_id"],
                    RecipeVersion.menu_product_id == ctx["menu_id"],
                ))
            else:
                db.add(SalesRecord(company_id=ctx["company_id"], branch_id=branch_id,
                    source_upload_id=upload.id, product_id=ctx["menu_id"],
                    recipe_version_id=shared_recipe.id, business_date=DAY1,
                    granularity="AGGREGATED", aggregate_id=f"SCOPE-{uuid4()}",
                    source_identity=f"SCOPE-{uuid4()}", quantity=Decimal("1"),
                    unit_price=Decimal("10"), discount_amount=Decimal(0),
                    tax_amount=Decimal(0), net_amount=Decimal("10"),
                    sales_channel="IN_STORE"))
        db.commit()
        branch_scope = resolve_branch_scope(db, manager)
        data = load_actual_consumption_inputs(db, ctx["company_id"], DAY1,
            DAY1, branch_scope, ctx["ingredient_id"])

    permitted = {ctx["branches"][0]}
    assert {branch.id for branch in data["branches"]} == permitted
    assert {upload.branch_id for upload in data["uploads"]} == permitted
    assert {scope.branch_id for scope in data["theoretical_scopes"]} == permitted
    assert {sale.branch_id for sale in data["theoretical_sales"]} == permitted
    theoretical = calculate_theoretical_consumption(data["theoretical_scopes"],
        data["theoretical_sales"], ctx["company_id"])
    data["theoretical_scopes"] = theoretical["scopes"]
    data["theoretical_items"] = theoretical["items"]
    result = calculate_actual_consumption(data, ctx["company_id"], DAY1, DAY1,
        None, ctx["ingredient_id"])
    assert {item["branch_id"] for item in result["items"]} == permitted


def test_unit_mismatch_and_unknown_purchase_unit_are_not_silently_used(test_environment):
    client, sessions = test_environment
    ctx = setup_company(client, sessions)
    with sessions() as db:
        upload = add_upload(db, ctx, ctx["branches"][0], DAY1)
        snapshot = add_snapshot(db, ctx, upload)
        snapshot.unit = "kg"
        add_coverage(db, ctx, upload)
        db.commit()
    row = request_actual(client, ctx["token"]).json()["items"][0]
    assert row["status"] == "UNIT_MISMATCH"
    assert row["actual_stock_depletion"] is None


def test_voided_manual_movement_is_excluded(test_environment):
    client, sessions = test_environment
    ctx = setup_company(client, sessions)
    with sessions() as db:
        upload = add_upload(db, ctx, ctx["branches"][0], DAY1)
        add_snapshot(db, ctx, upload, opening="100", closing="100")
        add_movement(db, ctx, upload.branch_id, "WASTE", "5", voided=True)
        add_coverage(db, ctx, upload, states={"WASTE": "NOT_APPLICABLE"})
        db.commit()
    row = request_actual(client, ctx["token"]).json()["items"][0]
    assert row["status"] == "COMPLETE"
    assert Decimal(row["total_outflows"]) == 0
    assert Decimal(row["actual_sales_related_consumption"]) == 0


def test_superseded_upload_movements_are_excluded(test_environment):
    client, sessions = test_environment
    ctx = setup_company(client, sessions)
    branch = ctx["branches"][0]
    with sessions() as db:
        old = add_upload(db, ctx, branch, DAY1, current=False)
        add_movement(db, ctx, branch, "OTHER_INFLOW", "50", upload=old)
        current = add_upload(db, ctx, branch, DAY1, version=2, current=True)
        add_snapshot(db, ctx, current, opening="100", closing="100")
        add_coverage(db, ctx, current)
        db.commit()
    row = request_actual(client, ctx["token"]).json()["items"][0]
    assert row["status"] == "COMPLETE"
    assert Decimal(row["total_inflows"]) == 0
    assert row["source_uploads"] == [{"upload_id": row["source_uploads"][0]["upload_id"], "version": 2}]


def test_transfer_legs_are_visible_by_branch_and_net_at_company_scope(test_environment):
    client, sessions = test_environment
    ctx = setup_company(client, sessions, branches=2)
    source_id, destination_id = ctx["branches"]
    with sessions() as db:
        source_upload = add_upload(db, ctx, source_id, DAY1)
        destination_upload = add_upload(db, ctx, destination_id, DAY1)
        add_snapshot(db, ctx, source_upload, opening="100", closing="90")
        add_snapshot(db, ctx, destination_upload, opening="50", closing="55")
        add_coverage(db, ctx, source_upload, states={"TRANSFER_OUT": "COMPLETE"})
        add_coverage(db, ctx, destination_upload, states={"TRANSFER_IN": "COMPLETE"})
        transfer = StockTransfer(company_id=ctx["company_id"],
            ingredient_product_id=ctx["ingredient_id"], source_branch_id=source_id,
            destination_branch_id=destination_id, movement_date=DAY1,
            quantity=Decimal("10"), unit="g", source_batch_number=None,
            destination_batch_number=None, created_by_user_id=ctx["user_id"])
        db.add(transfer)
        db.flush()
        add_movement(db, ctx, source_id, "TRANSFER_OUT", "10", transfer_id=transfer.id)
        add_movement(db, ctx, destination_id, "TRANSFER_IN", "10", transfer_id=transfer.id)
        db.commit()
    response = request_actual(client, ctx["token"])
    rows = response.json()["items"]
    source = next(row for row in rows if row["branch_id"] == str(source_id))
    destination = next(row for row in rows if row["branch_id"] == str(destination_id))
    company = response.json()["company_totals"][0]
    assert Decimal(source["total_outflows"]) == 10
    assert Decimal(source["known_non_sales_outflows"]) == 10
    assert Decimal(destination["total_inflows"]) == 10
    assert Decimal(destination["actual_sales_related_consumption"]) == 5
    assert Decimal(company["opening_stock"]) == 150
    assert Decimal(company["closing_stock"]) == 145
    assert Decimal(company["total_inflows"]) == 0
    assert Decimal(company["total_outflows"]) == 0
    assert Decimal(company["known_non_sales_outflows"]) == 0
    assert Decimal(company["actual_sales_related_consumption"]) == 5


def test_incomplete_transfer_pair_is_invalid(test_environment):
    client, sessions = test_environment
    ctx = setup_company(client, sessions, branches=2)
    source_id = ctx["branches"][0]
    with sessions() as db:
        upload = add_upload(db, ctx, source_id, DAY1)
        add_snapshot(db, ctx, upload)
        add_coverage(db, ctx, upload, states={"TRANSFER_OUT": "COMPLETE"})
        transfer = StockTransfer(company_id=ctx["company_id"],
            ingredient_product_id=ctx["ingredient_id"], source_branch_id=source_id,
            destination_branch_id=ctx["branches"][1], movement_date=DAY1,
            quantity=Decimal("10"), unit="g", source_batch_number=None,
            destination_batch_number=None, created_by_user_id=ctx["user_id"])
        db.add(transfer)
        db.flush()
        add_movement(db, ctx, source_id, "TRANSFER_OUT", "10", transfer_id=transfer.id)
        db.commit()
    row = request_actual(client, ctx["token"],
        f"start_date={DAY1}&end_date={DAY1}&branch_id={source_id}").json()["items"][0]
    assert row["status"] == "INVALID_DATA"
    assert "INVALID_TRANSFER_PAIR" in row["reason_codes"]


def test_incomplete_theoretical_data_keeps_comparison_null(test_environment):
    client, sessions = test_environment
    ctx = setup_company(client, sessions)
    with sessions() as db:
        upload = add_upload(db, ctx, ctx["branches"][0], DAY1)
        add_snapshot(db, ctx, upload)
        add_coverage(db, ctx, upload)
        add_theory(db, ctx, upload, missing_recipe=True)
        db.commit()
    row = request_actual(client, ctx["token"]).json()["items"][0]
    assert row["status"] == "COMPLETE"
    assert row["theoretical_status"] == "INCOMPLETE"
    assert row["theoretical_consumption"] is None
    assert row["absolute_variance"] is None
    assert row["variance_percent"] is None


def test_api_keeps_owner_only_tenant_and_branch_validation(test_environment):
    client, sessions = test_environment
    ctx = setup_company(client, sessions)
    other = setup_company(client, sessions, email="another-actual@example.com")
    foreign_branch = other["branches"][0]
    assert request_actual(client, ctx["token"],
        f"start_date={DAY1}&end_date={DAY1}&branch_id={foreign_branch}").status_code == 404
    assert request_actual(client, ctx["token"],
        f"start_date={DAY1}&end_date={DAY1}&ingredient_id={other['ingredient_id']}").status_code == 404
    with sessions() as db:
        membership = db.get(CompanyMembership, ctx["membership_id"])
        membership.role = "STAFF"
        db.commit()
    assert request_actual(client, ctx["token"]).status_code == 403

