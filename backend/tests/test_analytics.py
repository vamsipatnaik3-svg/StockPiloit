from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select
from app.core.security import hash_password

from app.models import (Branch, CompanyMembership, DailyUpload, InventorySnapshot,
    AnalystAnalyticsGrant, AnalystAnalyticsGrantBranch, BranchMembership,
    Product, PurchaseLine, SalesRecord, StockCoverageDeclaration, User,
    StockMovement, StockMovementReasonCode)

PASSWORD = "StockPilot_Test_123!"


def owner(client, email, company):
    response = client.post("/api/v1/auth/register", json={
        "full_name": "Analytics Owner", "email": email, "password": PASSWORD,
        "company_name": company, "industry": "grocery", "country_code": "IN",
        "currency": "INR", "timezone": "Asia/Kolkata",
    })
    assert response.status_code == 201
    login = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200
    return login.cookies.get("stockpilot_session"), response.json()["company_id"]


def seed_base(sessions, company_id):
    from uuid import UUID
    company_id = UUID(company_id)
    with sessions() as db:
        from uuid import UUID
        membership = db.scalar(select(CompanyMembership).where(
            CompanyMembership.company_id == company_id))
        branch = Branch(company_id=company_id, name="Central", code="CEN",
            country_code="IN", timezone="Asia/Kolkata")
        product = Product(company_id=company_id, sku="TEA-1", product_name="Tea",
            unit_of_measure="kg")
        db.add_all([branch, product]); db.flush()
        upload = DailyUpload(company_id=company_id, branch_id=branch.id,
            business_date=date(2026, 11, 25), uploaded_by_membership_id=membership.id,
            object_key=f"test/{uuid4()}", original_filename="test.xlsx",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            file_size_bytes=100, version=1, status="UPLOADED", is_current=True,
            processing_status="COMPLETED")
        db.add(upload); db.flush()
        aggregate_upload = DailyUpload(company_id=company_id, branch_id=branch.id,
            business_date=date(2026, 11, 24), uploaded_by_membership_id=membership.id,
            object_key=f"test/{uuid4()}", original_filename="aggregate.xlsx",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            file_size_bytes=100, version=1, status="UPLOADED", is_current=True,
            processing_status="COMPLETED")
        db.add(aggregate_upload); db.flush()
        db.add_all([
            SalesRecord(company_id=company_id, branch_id=branch.id, source_upload_id=upload.id,
                product_id=product.id, business_date=upload.business_date,
                granularity="TRANSACTION", transaction_id="T-1", line_id="1",
                source_identity="transaction:T-1:1", quantity=Decimal("2"),
                unit_price=Decimal("10"), discount_amount=Decimal("0"),
                tax_amount=Decimal("0"), net_amount=Decimal("20")),
            SalesRecord(company_id=company_id, branch_id=branch.id, source_upload_id=upload.id,
                product_id=product.id, business_date=upload.business_date,
                granularity="TRANSACTION", transaction_id="T-1", line_id="2",
                source_identity="transaction:T-1:2", quantity=Decimal("1"),
                unit_price=Decimal("5"), discount_amount=Decimal("0"),
                tax_amount=Decimal("0"), net_amount=Decimal("5")),
            SalesRecord(company_id=company_id, branch_id=branch.id,
                source_upload_id=aggregate_upload.id, product_id=product.id,
                business_date=aggregate_upload.business_date, granularity="AGGREGATED",
                aggregate_id="A-1", source_identity="aggregate:A-1", quantity=Decimal("2"),
                unit_price=Decimal("6"), discount_amount=Decimal("0"),
                tax_amount=Decimal("0"), net_amount=Decimal("12")),
            InventorySnapshot(company_id=company_id, branch_id=branch.id,
                source_upload_id=upload.id, product_id=product.id,
                business_date=upload.business_date, batch_number="B1",
                opening_quantity=Decimal("10"), closing_quantity=Decimal("7"), unit="kg",
                expiry_date=date(2026, 12, 1), unit_cost=Decimal("3"),
                damaged_quantity=Decimal("1"), wasted_quantity=Decimal("2")),
            PurchaseLine(company_id=company_id, branch_id=branch.id,
                source_upload_id=upload.id, product_id=product.id, receipt_id="R1",
                receipt_line_id="1", business_date=upload.business_date,
                receipt_date=upload.business_date, supplier_name="Supplier A",
                quantity_received=Decimal("4"), unit_purchase_price=Decimal("2")),
        ])
        db.commit()
        return branch.id, product.id


def test_analytics_revenue_transactions_branch_and_tenant_scoping(test_environment):
    client, sessions = test_environment
    token, company_id = owner(client, "analytics-a@example.com", "Analytics A")
    other_token, _ = owner(client, "analytics-b@example.com", "Analytics B")
    branch_id, _ = seed_base(sessions, company_id)
    query = "?start_date=2026-11-24&end_date=2026-11-25"
    response = client.get("/api/v1/analytics/overview" + query,
        cookies={"stockpilot_session": token})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["revenue"]["current"] == "37.0000"
    assert body["transaction_count"]["current"] == 1
    assert body["coverage"]["sales_lines"] == 3
    assert body["sales_coverage"]["status"] == "COMPLETE"
    assert body["sales_coverage"]["sales_available_branch_days"] == 2
    assert body["sales_coverage"]["confirmed_zero_sales_branch_days"] == 0
    branches = client.get("/api/v1/analytics/branches/performance" + query,
        cookies={"stockpilot_session": token})
    assert branches.status_code == 200, branches.text
    assert branches.json()["branches"][0]["previous_revenue"] is None
    products = client.get("/api/v1/analytics/products/performance" + query,
        cookies={"stockpilot_session": token})
    assert products.status_code == 200, products.text
    assert len(products.json()["product_trends"]) == 2
    assert client.get("/api/v1/analytics/overview" + query + f"&branch_id={branch_id}",
        cookies={"stockpilot_session": token}).json()["revenue"]["current"] == "37.0000"
    assert client.get("/api/v1/analytics/overview" + query,
        cookies={"stockpilot_session": other_token}).json()["revenue"]["current"] is None
    assert client.get("/api/v1/analytics/overview?start_date=2026-11-26&end_date=2026-11-25",
        cookies={"stockpilot_session": token}).status_code == 422


def test_analytics_inventory_waste_purchase_and_units(test_environment):
    client, sessions = test_environment
    token, company_id = owner(client, "analytics-data@example.com", "Analytics Data")
    seed_base(sessions, company_id)
    params = "?start_date=2026-11-25&end_date=2026-11-25"
    headers = {"stockpilot_session": token}
    inventory = client.get("/api/v1/analytics/inventory/overview?as_of_date=2026-11-25", cookies=headers)
    assert inventory.status_code == 200, inventory.text
    assert inventory.json()["products"][0]["quantity"] == "7.0000"
    assert inventory.json()["products"][0]["unit"] == "kg"
    assert len(inventory.json()["expiring_batches"]) == 1
    waste = client.get("/api/v1/analytics/waste/overview" + params, cookies=headers)
    assert waste.status_code == 200, waste.text
    assert Decimal(waste.json()["recorded_value"]) == Decimal("9")
    assert waste.json()["trend"][0]["unit"] == "kg"
    assert waste.json()["damaged_by_product"][0]["damaged"] == "1.0000"
    assert waste.json()["wasted_by_product"][0]["wasted"] == "2.0000"
    assert waste.json()["quantity_coverage_status"] == "PARTIAL"
    purchase = client.get("/api/v1/analytics/purchases/overview" + params, cookies=headers)
    assert purchase.status_code == 200, purchase.text
    assert purchase.json()["spend"] == "8.0000"


def test_purchase_spend_uses_receipt_date_and_groups_multiple_receipt_dates(test_environment):
    client, sessions = test_environment
    token, company_id = owner(client, "receipt-date@example.com", "Receipt Date")
    branch_id, product_id = seed_base(sessions, company_id)
    with sessions() as db:
        line = db.scalar(select(PurchaseLine).where(PurchaseLine.branch_id == branch_id))
        line.receipt_date = date(2026, 11, 26)
        second = PurchaseLine(company_id=line.company_id, branch_id=line.branch_id,
            source_upload_id=line.source_upload_id, product_id=line.product_id,
            receipt_id="R2", receipt_line_id="1", business_date=line.business_date,
            receipt_date=date(2026, 11, 27), supplier_name="Supplier B",
            quantity_received=Decimal("3"), unit_purchase_price=Decimal("4"))
        db.add(second)
        db.commit()
    headers = {"stockpilot_session": token}
    at_receipt = client.get("/api/v1/analytics/purchases/overview?start_date=2026-11-26&end_date=2026-11-26",
        cookies=headers).json()
    assert at_receipt["spend"] == "8.0000"
    assert at_receipt["total_lines"] == 1
    assert at_receipt["trend"] == [{"receipt_date": "2026-11-26", "spend": "8.0000"}]
    other_receipt = client.get("/api/v1/analytics/purchases/overview?start_date=2026-11-27&end_date=2026-11-27",
        cookies=headers).json()
    assert other_receipt["spend"] == "12.0000"
    assert other_receipt["trend"][0]["receipt_date"] == "2026-11-27"


def test_purchase_spend_is_unavailable_when_receipt_date_is_missing():
    from app.services.analytics import _purchase_spend_result

    spend, status = _purchase_spend_result(
        total_lines=2, priced_lines=2, known_spend=Decimal("20"),
        missing_receipt_dates=1)
    assert spend is None
    assert status == "PARTIAL"


def test_purchase_receipt_date_filter_applies_to_branch_and_company_scope(test_environment):
    client, sessions = test_environment
    token, company_id = owner(client, "receipt-branch@example.com", "Receipt Branch")
    first_branch, product_id = seed_base(sessions, company_id)
    with sessions() as db:
        membership = db.scalar(select(CompanyMembership).where(
            CompanyMembership.company_id == UUID(company_id)))
        first_line = db.scalar(select(PurchaseLine).where(PurchaseLine.branch_id == first_branch))
        first_line.receipt_date = date(2026, 11, 26)
        second_branch = Branch(company_id=UUID(company_id), name="Harbor", code="HAR",
            country_code="IN", timezone="Asia/Kolkata")
        db.add(second_branch); db.flush()
        upload = DailyUpload(company_id=UUID(company_id), branch_id=second_branch.id,
            business_date=date(2026, 11, 25), uploaded_by_membership_id=membership.id,
            object_key=f"test/{uuid4()}", original_filename="second-branch.xlsx",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            file_size_bytes=100, version=1, status="UPLOADED", is_current=True,
            processing_status="COMPLETED")
        db.add(upload); db.flush()
        db.add(PurchaseLine(company_id=UUID(company_id), branch_id=second_branch.id,
            source_upload_id=upload.id, product_id=product_id, receipt_id="RB-1",
            receipt_line_id="1", business_date=upload.business_date,
            receipt_date=date(2026, 11, 26), supplier_name="Supplier C",
            quantity_received=Decimal("2"), unit_purchase_price=Decimal("5")))
        db.commit()
        second_branch_id = second_branch.id
    headers = {"stockpilot_session": token}
    url = "/api/v1/analytics/purchases/overview?start_date=2026-11-26&end_date=2026-11-26"
    company = client.get(url, cookies=headers).json()
    first = client.get(url + f"&branch_id={first_branch}", cookies=headers).json()
    second = client.get(url + f"&branch_id={second_branch_id}", cookies=headers).json()
    assert company["spend"] == "18.0000"
    assert first["spend"] == "8.0000"
    assert second["spend"] == "10.0000"


def test_purchase_spend_uses_only_current_corrected_upload_version(test_environment):
    client, sessions = test_environment
    token, company_id = owner(client, "receipt-correction@example.com", "Receipt Correction")
    branch_id, product_id = seed_base(sessions, company_id)
    with sessions() as db:
        membership = db.scalar(select(CompanyMembership).where(
            CompanyMembership.company_id == UUID(company_id)))
        old_upload = db.scalar(select(DailyUpload).where(
            DailyUpload.branch_id == branch_id,
            DailyUpload.business_date == date(2026, 11, 25)))
        old_line = db.scalar(select(PurchaseLine).where(
            PurchaseLine.source_upload_id == old_upload.id))
        old_upload.is_current = False
        replacement = DailyUpload(company_id=UUID(company_id), branch_id=branch_id,
            business_date=old_upload.business_date,
            uploaded_by_membership_id=membership.id, object_key=f"test/{uuid4()}",
            original_filename="correction.xlsx",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            file_size_bytes=100, version=2, status="UPLOADED", is_current=True,
            processing_status="COMPLETED")
        db.add(replacement); db.flush()
        db.add(PurchaseLine(company_id=UUID(company_id), branch_id=branch_id,
            source_upload_id=replacement.id, product_id=product_id,
            receipt_id=old_line.receipt_id, receipt_line_id=old_line.receipt_line_id,
            business_date=replacement.business_date, receipt_date=date(2026, 11, 26),
            supplier_name="Supplier A", quantity_received=Decimal("6"),
            unit_purchase_price=Decimal("3")))
        db.commit()
    headers = {"stockpilot_session": token}
    date_25 = client.get("/api/v1/analytics/purchases/overview?start_date=2026-11-25&end_date=2026-11-25",
        cookies=headers).json()
    date_26 = client.get("/api/v1/analytics/purchases/overview?start_date=2026-11-26&end_date=2026-11-26",
        cookies=headers).json()
    assert date_25["spend"] == "0"
    assert date_25["total_lines"] == 0
    assert date_26["spend"] == "18.0000"
    assert date_26["total_lines"] == 1


def test_transaction_count_reports_source_granularity_and_branch_coverage(test_environment):
    client, sessions = test_environment
    token, company_id = owner(client, "transaction-coverage@example.com", "Transaction Coverage")
    branch_id, product_id = seed_base(sessions, company_id)
    with sessions() as db:
        membership = db.scalar(select(CompanyMembership).where(
            CompanyMembership.company_id == UUID(company_id)))
        second_branch = Branch(company_id=UUID(company_id), name="Riverside", code="RIV",
            country_code="IN", timezone="Asia/Kolkata")
        db.add(second_branch); db.flush()
        upload = DailyUpload(company_id=UUID(company_id), branch_id=second_branch.id,
            business_date=date(2026, 11, 25), uploaded_by_membership_id=membership.id,
            object_key=f"test/{uuid4()}", original_filename="transaction.xlsx",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            file_size_bytes=100, version=1, status="UPLOADED", is_current=True,
            processing_status="COMPLETED")
        db.add(upload); db.flush()
        db.add(SalesRecord(company_id=UUID(company_id), branch_id=second_branch.id,
            source_upload_id=upload.id, product_id=product_id,
            business_date=upload.business_date, granularity="TRANSACTION",
            transaction_id="T-1", line_id="1", source_identity="transaction:T-1:1",
            quantity=Decimal("1"), unit_price=Decimal("10"),
            discount_amount=Decimal("0"), tax_amount=Decimal("0"),
            net_amount=Decimal("10")))
        db.commit()
        second_branch_id = second_branch.id
    headers = {"stockpilot_session": token}
    overview = client.get("/api/v1/analytics/overview?start_date=2026-11-24&end_date=2026-11-25",
        cookies=headers).json()
    assert overview["transaction_count"]["current"] == 2
    assert overview["transaction_count"]["change_percent"] is None
    assert overview["transaction_count_coverage"] == {
        "current": "PARTIAL", "previous": "UNAVAILABLE"}
    branches = client.get("/api/v1/analytics/branches/performance?start_date=2026-11-24&end_date=2026-11-25",
        cookies=headers).json()["branches"]
    branch_rows = {row["branch_id"]: row for row in branches}
    assert branch_rows[str(branch_id)]["transaction_count"] == 1
    assert branch_rows[str(branch_id)]["transaction_count_coverage_status"] == "PARTIAL"
    assert branch_rows[str(second_branch_id)]["transaction_count"] == 1
    assert branch_rows[str(second_branch_id)]["transaction_count_coverage_status"] == "COMPLETE"
    transaction_only = client.get("/api/v1/analytics/overview?start_date=2026-11-25&end_date=2026-11-25",
        cookies=headers).json()
    assert transaction_only["transaction_count"]["current"] == 2
    assert transaction_only["transaction_count_coverage"]["current"] == "COMPLETE"
    aggregate_only = client.get("/api/v1/analytics/overview?start_date=2026-11-24&end_date=2026-11-24",
        cookies=headers).json()
    assert aggregate_only["transaction_count"]["current"] is None
    assert aggregate_only["transaction_count_coverage"]["current"] == "UNAVAILABLE"
    branch_only = client.get(
        f"/api/v1/analytics/overview?start_date=2026-11-25&end_date=2026-11-25&branch_id={branch_id}",
        cookies=headers).json()
    assert branch_only["transaction_count_coverage"]["current"] == "COMPLETE"
    company_only = client.get("/api/v1/analytics/overview?start_date=2026-11-25&end_date=2026-11-25",
        cookies=headers).json()
    assert company_only["transaction_count"]["current"] == 2
    assert company_only["transaction_count_coverage"]["current"] == "COMPLETE"


def test_analytics_owner_authorization_and_empty_data(test_environment):
    client, sessions = test_environment
    token, company_id = owner(client, "analytics-role@example.com", "Analytics Role")
    empty = client.get("/api/v1/analytics/overview?start_date=2026-11-25&end_date=2026-11-25",
        cookies={"stockpilot_session": token})
    assert empty.status_code == 200
    assert empty.json()["revenue"]["current"] is None
    assert empty.json()["transaction_count"]["current"] is None
    assert empty.json()["sales_coverage"]["status"] == "UNAVAILABLE"
    assert empty.json()["sales_coverage"]["evaluated_branch_days"] == 0
    with sessions() as db:
        from uuid import UUID
        membership = db.scalar(select(CompanyMembership).where(
            CompanyMembership.company_id == UUID(company_id)))
        membership.role = "ANALYST"; db.commit()
    response = client.get("/api/v1/analytics/overview", cookies={"stockpilot_session": token})
    assert response.status_code == 403
    with sessions() as db:
        membership = db.scalar(select(CompanyMembership).where(
            CompanyMembership.company_id == UUID(company_id)))
        membership.role = "MANAGER"
        db.commit()
    manager_response = client.get("/api/v1/analytics/overview",
        cookies={"stockpilot_session": token})
    # Managers with no assigned active branches fail closed rather than seeing
    # the company-wide result.
    assert manager_response.status_code == 403


ANALYTICS_ENDPOINTS = [
    "/api/v1/analytics/overview?start_date=2026-11-25&end_date=2026-11-25",
    "/api/v1/analytics/sales/trends?start_date=2026-11-25&end_date=2026-11-25",
    "/api/v1/analytics/branches/performance?start_date=2026-11-25&end_date=2026-11-25",
    "/api/v1/analytics/products/performance?start_date=2026-11-25&end_date=2026-11-25",
    "/api/v1/analytics/inventory/overview?as_of_date=2026-11-25",
    "/api/v1/analytics/inventory/expiry?as_of_date=2026-11-25",
    "/api/v1/analytics/waste/overview?start_date=2026-11-25&end_date=2026-11-25",
    "/api/v1/analytics/purchases/overview?start_date=2026-11-25&end_date=2026-11-25",
    "/api/v1/analytics/alerts?start_date=2026-11-25&end_date=2026-11-25",
    "/api/v1/analytics/ingredient-consumption/theoretical?start_date=2026-11-25&end_date=2026-11-25",
    "/api/v1/analytics/ingredient-consumption/actual?start_date=2026-11-25&end_date=2026-11-25",
    "/api/v1/analytics/variance/intelligence?start_date=2026-11-25&end_date=2026-11-25",
]


def _analytics_actor(sessions, company_id, role, email, assigned_branch_id=None):
    with sessions() as db:
        user = User(full_name=role.title(), email=email,
            password_hash=hash_password(PASSWORD), is_active=True)
        db.add(user); db.flush()
        member = CompanyMembership(company_id=UUID(str(company_id)),
            user_id=user.id, role=role)
        db.add(member); db.flush()
        if assigned_branch_id is not None:
            db.add(BranchMembership(branch_id=UUID(str(assigned_branch_id)),
                company_membership_id=member.id))
        db.commit()
        return member.id


def _login(client, email):
    response = client.post("/api/v1/auth/login", json={
        "email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return response.cookies.get("stockpilot_session")


def test_manager_and_selected_analyst_are_scoped_across_all_analytics_endpoints(test_environment):
    client, sessions = test_environment
    owner_token, company_id = owner(client, "scoped-analytics-owner@example.com", "Scoped Analytics")
    branch_id, product_id = seed_base(sessions, company_id)
    with sessions() as db:
        owner_member = db.scalar(select(CompanyMembership).where(
            CompanyMembership.company_id == UUID(company_id),
            CompanyMembership.role == "OWNER"))
        branch2 = Branch(company_id=UUID(company_id), name="Restricted", code="RST",
            country_code="IN", timezone="Asia/Kolkata")
        db.add(branch2); db.flush()
        upload = DailyUpload(company_id=UUID(company_id), branch_id=branch2.id,
            business_date=date(2026, 11, 25), uploaded_by_membership_id=owner_member.id,
            object_key=f"test/{uuid4()}", original_filename="other.xlsx",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            file_size_bytes=100, version=1, status="UPLOADED", is_current=True,
            processing_status="COMPLETED")
        db.add(upload); db.flush()
        db.add(SalesRecord(company_id=UUID(company_id), branch_id=branch2.id,
            source_upload_id=upload.id, product_id=UUID(str(product_id)),
            business_date=upload.business_date, granularity="AGGREGATED",
            aggregate_id="OTHER", source_identity="aggregate:OTHER",
            quantity=Decimal("100"), unit_price=Decimal("100"),
            discount_amount=Decimal("0"), tax_amount=Decimal("0"),
            net_amount=Decimal("10000")))
        db.commit()
        branch2_id = branch2.id

    manager_id = _analytics_actor(sessions, company_id, "MANAGER",
        "scoped-manager@example.com", branch_id)
    analyst_id = _analytics_actor(sessions, company_id, "ANALYST",
        "scoped-analyst@example.com", branch_id)
    with sessions() as db:
        owner_member = db.scalar(select(CompanyMembership).where(
            CompanyMembership.company_id == UUID(company_id),
            CompanyMembership.role == "OWNER"))
        analyst_grant = AnalystAnalyticsGrant(company_id=UUID(company_id),
            analyst_membership_id=analyst_id,
            granted_by_membership_id=owner_member.id, scope_type="BRANCHES")
        db.add(analyst_grant); db.flush()
        db.add(AnalystAnalyticsGrantBranch(grant_id=analyst_grant.id,
            company_id=UUID(company_id), branch_id=UUID(str(branch_id))))
        db.commit()

    manager_token = _login(client, "scoped-manager@example.com")
    analyst_token = _login(client, "scoped-analyst@example.com")
    for endpoint in ANALYTICS_ENDPOINTS:
        for token in (manager_token, analyst_token):
            response = client.get(endpoint, cookies={"stockpilot_session": token})
            assert response.status_code == 200, (endpoint, response.text)

    params = "?start_date=2026-11-25&end_date=2026-11-25"
    for token in (manager_token, analyst_token):
        overview_response = client.get("/api/v1/analytics/overview" + params,
            cookies={"stockpilot_session": token})
        assert overview_response.json()["revenue"]["current"] == "25.0000"
        branch_rows = client.get("/api/v1/analytics/branches/performance" + params,
            cookies={"stockpilot_session": token}).json()["branches"]
        assert [item["branch_id"] for item in branch_rows] == [str(branch_id)]
        for endpoint in ANALYTICS_ENDPOINTS:
            denied = client.get(endpoint + f"&branch_id={branch2_id}",
                cookies={"stockpilot_session": token})
            assert denied.status_code == 404, (endpoint, denied.text)
            mixed = client.get(endpoint +
                f"&branch_ids={branch_id}&branch_ids={branch2_id}",
                cookies={"stockpilot_session": token})
            assert mixed.status_code == 404, (endpoint, mixed.text)
        allowed_multi = client.get("/api/v1/analytics/overview" + params +
            f"&branch_ids={branch_id}", cookies={"stockpilot_session": token})
        assert allowed_multi.status_code == 200
        both_filters = client.get("/api/v1/analytics/overview" + params +
            f"&branch_id={branch_id}&branch_ids={branch_id}",
            cookies={"stockpilot_session": token})
        assert both_filters.status_code == 422

    owner_overview = client.get("/api/v1/analytics/overview" + params,
        cookies={"stockpilot_session": owner_token})
    assert owner_overview.json()["revenue"]["current"] == "10025.0000"


def test_analyst_grant_absence_revocation_and_staff_denied_on_every_analytics_endpoint(test_environment):
    client, sessions = test_environment
    owner_token, company_id = owner(client, "all-denial-owner@example.com", "Denial Analytics")
    branch_id, _ = seed_base(sessions, company_id)
    analyst_id = _analytics_actor(sessions, company_id, "ANALYST",
        "no-grant-analyst@example.com", branch_id)
    staff_id = _analytics_actor(sessions, company_id, "STAFF",
        "analytics-staff@example.com", branch_id)
    analyst_token = _login(client, "no-grant-analyst@example.com")
    staff_token = _login(client, "analytics-staff@example.com")
    for endpoint in ANALYTICS_ENDPOINTS:
        assert client.get(endpoint, cookies={"stockpilot_session": analyst_token}).status_code == 403
        assert client.get(endpoint, cookies={"stockpilot_session": staff_token}).status_code == 403

    with sessions() as db:
        owner_member = db.scalar(select(CompanyMembership).where(
            CompanyMembership.company_id == UUID(company_id),
            CompanyMembership.role == "OWNER"))
        grant = AnalystAnalyticsGrant(company_id=UUID(company_id),
            analyst_membership_id=analyst_id, granted_by_membership_id=owner_member.id,
            scope_type="COMPANY")
        db.add(grant); db.commit(); grant_id = grant.id
    assert client.get(ANALYTICS_ENDPOINTS[0],
        cookies={"stockpilot_session": analyst_token}).status_code == 200
    assert client.post(f"/api/v1/analyst-analytics-grants/{grant_id}/revoke",
        cookies={"stockpilot_session": owner_token}).status_code == 200
    assert client.get(ANALYTICS_ENDPOINTS[0],
        cookies={"stockpilot_session": analyst_token}).status_code == 403


def test_analyst_company_grant_is_company_scoped_and_cross_company_header_is_rejected(test_environment):
    client, sessions = test_environment
    owner_token, company_id = owner(client, "company-grant-owner@example.com", "Company Grant")
    branch_id, _ = seed_base(sessions, company_id)
    with sessions() as db:
        owner_member = db.scalar(select(CompanyMembership).where(
            CompanyMembership.company_id == UUID(company_id),
            CompanyMembership.role == "OWNER"))
        other_branch = Branch(company_id=UUID(company_id), name="Company Grant Branch 2",
            code="CG2", country_code="IN", timezone="Asia/Kolkata")
        db.add(other_branch); db.flush()
        upload = DailyUpload(company_id=UUID(company_id), branch_id=other_branch.id,
            business_date=date(2026, 11, 25), uploaded_by_membership_id=owner_member.id,
            object_key=f"test/{uuid4()}", original_filename="company.xlsx",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            file_size_bytes=100, version=1, status="UPLOADED", is_current=True,
            processing_status="COMPLETED")
        db.add(upload); db.flush()
        product = db.scalar(select(Product).where(Product.company_id == UUID(company_id)))
        db.add(SalesRecord(company_id=UUID(company_id), branch_id=other_branch.id,
            source_upload_id=upload.id, product_id=product.id,
            business_date=upload.business_date, granularity="AGGREGATED",
            aggregate_id="COMPANY-OTHER", source_identity="aggregate:COMPANY-OTHER",
            quantity=Decimal("5"), unit_price=Decimal("50"),
            discount_amount=Decimal("0"), tax_amount=Decimal("0"),
            net_amount=Decimal("250")))
        db.commit()
    other_token, other_company_id = owner(client, "other-grant-owner@example.com", "Other Grant")
    analyst_id = _analytics_actor(sessions, company_id, "ANALYST",
        "company-grant-analyst@example.com")
    with sessions() as db:
        owner_member = db.scalar(select(CompanyMembership).where(
            CompanyMembership.company_id == UUID(company_id),
            CompanyMembership.role == "OWNER"))
        db.add(AnalystAnalyticsGrant(company_id=UUID(company_id),
            analyst_membership_id=analyst_id, granted_by_membership_id=owner_member.id,
            scope_type="COMPANY"))
        db.commit()
    analyst_token = _login(client, "company-grant-analyst@example.com")
    params = "?start_date=2026-11-25&end_date=2026-11-25"
    result = client.get("/api/v1/analytics/overview" + params,
        cookies={"stockpilot_session": analyst_token})
    assert result.status_code == 200, result.text
    assert result.json()["revenue"]["current"] == "275.0000"
    assert client.get("/api/v1/analytics/overview" + params,
        cookies={"stockpilot_session": analyst_token},
        headers={"X-Company-ID": other_company_id}).status_code == 403
    assert client.get("/api/v1/analytics/overview" + params +
        f"&branch_ids={branch_id}", cookies={"stockpilot_session": analyst_token}).status_code == 200


def test_manager_and_selected_analyst_analytics_deny_deactivated_branches(test_environment):
    client, sessions = test_environment
    owner_token, company_id = owner(client, "inactive-analytics-owner@example.com",
        "Inactive Analytics")
    branch_id, _ = seed_base(sessions, company_id)
    manager_id = _analytics_actor(sessions, company_id, "MANAGER",
        "inactive-analytics-manager@example.com", branch_id)
    analyst_id = _analytics_actor(sessions, company_id, "ANALYST",
        "inactive-analytics-analyst@example.com")
    with sessions() as db:
        owner_member = db.scalar(select(CompanyMembership).where(
            CompanyMembership.company_id == UUID(company_id),
            CompanyMembership.role == "OWNER"))
        grant = AnalystAnalyticsGrant(company_id=UUID(company_id),
            analyst_membership_id=analyst_id,
            granted_by_membership_id=owner_member.id, scope_type="BRANCHES")
        db.add(grant); db.flush()
        db.add(AnalystAnalyticsGrantBranch(grant_id=grant.id,
            company_id=UUID(company_id), branch_id=UUID(str(branch_id))))
        db.get(Branch, UUID(str(branch_id))).is_active = False
        db.commit()
    manager_token = _login(client, "inactive-analytics-manager@example.com")
    analyst_token = _login(client, "inactive-analytics-analyst@example.com")
    for token in (manager_token, analyst_token):
        response = client.get("/api/v1/analytics/overview",
            cookies={"stockpilot_session": token})
        assert response.status_code == 403


def add_waste_evidence(db, company_id, branch_id, product_id, *, kind, quantity,
        origin="MANUAL", upload=None, voided=False, reason_code=None):
    membership = db.scalar(select(CompanyMembership).where(
        CompanyMembership.company_id == company_id))
    reason_code = reason_code or {
        "WASTE": "WASTE_SPOILAGE", "DAMAGE": "DAMAGE_STORAGE",
        "NEGATIVE_ADJUSTMENT": "ADJUSTMENT_TEST",
    }[kind]
    if db.get(StockMovementReasonCode, (reason_code, kind)) is None:
        db.add(StockMovementReasonCode(code=reason_code, movement_type=kind,
            label=reason_code.replace("_", " ").title()))
        db.flush()
    db.add(StockMovement(
        company_id=company_id, branch_id=branch_id,
        ingredient_product_id=product_id, movement_date=date(2026, 11, 25),
        movement_type=kind, quantity=Decimal(str(quantity)), unit="kg",
        source_upload_id=upload.id if origin == "UPLOAD" else None,
        purchase_line_id=None, transfer_id=None, origin_type=origin,
        physical_event_id=uuid4(), reason_code=reason_code,
        created_by_user_id=None if origin == "UPLOAD" else membership.user_id,
        voided_by_user_id=membership.user_id if voided else None,
        voided_at=datetime.now(timezone.utc) if voided else None,
        void_reason="Entered in error" if voided else None,
    ))


def add_waste_category_coverage(db, upload, product_id, *, kind, status="COMPLETE"):
    db.add(StockCoverageDeclaration(
        company_id=upload.company_id, branch_id=upload.branch_id,
        business_date=upload.business_date, source_upload_id=upload.id,
        ingredient_product_id=product_id, unit="kg",
        coverage_dimension="MOVEMENT_CATEGORY", scope_type="INGREDIENT",
        movement_type=kind, status=status,
    ))


def add_inventory_coverage(db, upload, product, *, status="COMPLETE"):
    for dimension, scope_type in (
        ("INGREDIENT", "INGREDIENT"),
        ("BATCH", "ALL_BATCHES"),
        ("CLOSING_STOCK", "INGREDIENT"),
    ):
        db.add(StockCoverageDeclaration(
            company_id=upload.company_id, branch_id=upload.branch_id,
            business_date=upload.business_date, source_upload_id=upload.id,
            ingredient_product_id=product.id, unit=product.unit_of_measure,
            coverage_dimension=dimension, scope_type=scope_type,
            status=status,
        ))


def overview_response(client, token, *, start="2026-11-25", end="2026-11-25"):
    return client.get(f"/api/v1/analytics/overview?start_date={start}&end_date={end}",
        cookies={"stockpilot_session": token})


def test_sales_coverage_distinguishes_zero_missing_and_incomplete_uploads(test_environment):
    client, sessions = test_environment
    token, company_id = owner(client, "sales-coverage@example.com", "Sales Coverage")
    branch_id, product_id = seed_base(sessions, company_id)
    with sessions() as db:
        membership = db.scalar(select(CompanyMembership).where(
            CompanyMembership.company_id == UUID(company_id)))
        zero_upload = DailyUpload(company_id=UUID(company_id), branch_id=branch_id,
            business_date=date(2026, 11, 26), uploaded_by_membership_id=membership.id,
            object_key=f"test/{uuid4()}", original_filename="zero.xlsx",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            file_size_bytes=100, version=1, status="UPLOADED", is_current=True,
            processing_status="COMPLETED")
        incomplete_upload = DailyUpload(company_id=UUID(company_id), branch_id=branch_id,
            business_date=date(2026, 11, 27), uploaded_by_membership_id=membership.id,
            object_key=f"test/{uuid4()}", original_filename="failed.xlsx",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            file_size_bytes=100, version=1, status="FAILED", is_current=False,
            processing_status="VALIDATION_FAILED")
        db.add_all([zero_upload, incomplete_upload]); db.commit()
    response = overview_response(client, token, start="2026-11-25", end="2026-11-28")
    assert response.status_code == 200, response.text
    coverage = response.json()["sales_coverage"]
    assert coverage["status"] == "INCOMPLETE"
    assert coverage["evaluated_branch_days"] == 4
    assert coverage["sales_available_branch_days"] == 1
    assert coverage["confirmed_zero_sales_branch_days"] == 1
    assert coverage["incomplete_upload_branch_days"] == 1
    assert coverage["missing_upload_branch_days"] == 1
    branch = coverage["branches"][0]
    assert branch["incomplete_upload_dates"] == ["2026-11-27"]
    assert branch["missing_upload_dates"] == ["2026-11-28"]


def test_overview_waste_reuses_snapshot_only_coverage_and_unit_rules(test_environment):
    client, sessions = test_environment
    token, company_id = owner(client, "overview-snapshot-waste@example.com", "Overview Snapshot Waste")
    seed_base(sessions, company_id)
    response = overview_response(client, token)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["waste_coverage_status"] == "PARTIAL"
    assert body["waste_quantity"] is None
    assert body["waste_by_unit"] == [{
        "unit": "kg", "quantity": None, "damaged": "1.0000",
        "wasted": "2.0000", "coverage_status": "PARTIAL",
    }]


def test_overview_waste_uses_ledger_only_and_excludes_voided_movements(test_environment):
    client, sessions = test_environment
    token, company_id = owner(client, "overview-ledger-waste@example.com", "Overview Ledger Waste")
    branch_id, product_id = seed_base(sessions, company_id)
    with sessions() as db:
        upload = db.scalar(select(DailyUpload).where(
            DailyUpload.branch_id == branch_id, DailyUpload.is_current.is_(True),
            DailyUpload.business_date == date(2026, 11, 25)))
        snapshot = db.scalar(select(InventorySnapshot).where(
            InventorySnapshot.source_upload_id == upload.id))
        snapshot.damaged_quantity = Decimal("0")
        snapshot.wasted_quantity = Decimal("0")
        add_waste_category_coverage(db, upload, product_id, kind="WASTE")
        add_waste_category_coverage(db, upload, product_id, kind="DAMAGE")
        add_waste_evidence(db, UUID(company_id), branch_id, product_id,
            kind="WASTE", quantity="4.25")
        add_waste_evidence(db, UUID(company_id), branch_id, product_id,
            kind="DAMAGE", quantity="1.5")
        add_waste_evidence(db, UUID(company_id), branch_id, product_id,
            kind="WASTE", quantity="99", voided=True)
        db.commit()
    response = overview_response(client, token)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["waste_coverage_status"] == "COMPLETE"
    assert body["waste_quantity"] == "5.7500"
    assert body["waste_by_unit"][0]["quantity"] == "5.7500"


def test_overview_waste_overlap_is_not_double_counted(test_environment):
    client, sessions = test_environment
    token, company_id = owner(client, "overview-waste-overlap@example.com", "Overview Waste Overlap")
    branch_id, product_id = seed_base(sessions, company_id)
    with sessions() as db:
        upload = db.scalar(select(DailyUpload).where(
            DailyUpload.branch_id == branch_id, DailyUpload.is_current.is_(True),
            DailyUpload.business_date == date(2026, 11, 25)))
        snapshot = db.scalar(select(InventorySnapshot).where(
            InventorySnapshot.source_upload_id == upload.id))
        snapshot.damaged_quantity = Decimal("1.5")
        snapshot.wasted_quantity = Decimal("4.25")
        add_waste_category_coverage(db, upload, product_id, kind="WASTE")
        add_waste_category_coverage(db, upload, product_id, kind="DAMAGE")
        add_waste_evidence(db, UUID(company_id), branch_id, product_id,
            kind="WASTE", quantity="4.25")
        add_waste_evidence(db, UUID(company_id), branch_id, product_id,
            kind="DAMAGE", quantity="1.5")
        db.commit()
    response = overview_response(client, token)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["waste_coverage_status"] == "COMPLETE"
    assert body["waste_quantity"] == "5.7500"


def test_overview_waste_ledger_without_complete_coverage_is_partial(test_environment):
    client, sessions = test_environment
    token, company_id = owner(client, "overview-waste-partial@example.com", "Overview Waste Partial")
    branch_id, product_id = seed_base(sessions, company_id)
    with sessions() as db:
        snapshot = db.scalar(select(InventorySnapshot))
        snapshot.damaged_quantity = Decimal("0")
        snapshot.wasted_quantity = Decimal("0")
        add_waste_evidence(db, UUID(company_id), branch_id, product_id,
            kind="WASTE", quantity="3.25")
        db.commit()
    response = overview_response(client, token)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["waste_coverage_status"] == "PARTIAL"
    assert body["waste_quantity"] is None
    assert body["waste_by_unit"][0]["coverage_status"] == "PARTIAL"
    assert body["waste_by_unit"][0]["wasted"] == "3.2500"


def test_inventory_overview_exposes_complete_no_stock_and_unreported_coverage(test_environment):
    client, sessions = test_environment
    token, company_id = owner(client, "inventory-coverage@example.com", "Inventory Coverage")
    branch_id, _ = seed_base(sessions, company_id)
    with sessions() as db:
        upload = db.scalar(select(DailyUpload).where(
            DailyUpload.branch_id == branch_id, DailyUpload.is_current.is_(True),
            DailyUpload.business_date == date(2026, 11, 25)))
        complete = Product(company_id=UUID(company_id), sku="ING-COMPLETE",
            product_name="Complete ingredient", unit_of_measure="g", product_kind="INGREDIENT")
        no_stock = Product(company_id=UUID(company_id), sku="ING-NOSTOCK",
            product_name="No stock ingredient", unit_of_measure="g", product_kind="INGREDIENT")
        unreported = Product(company_id=UUID(company_id), sku="ING-UNKNOWN",
            product_name="Unreported ingredient", unit_of_measure="g", product_kind="INGREDIENT")
        partial = Product(company_id=UUID(company_id), sku="ING-PARTIAL",
            product_name="Partial ingredient", unit_of_measure="g", product_kind="INGREDIENT")
        db.add_all([complete, no_stock, unreported, partial]); db.flush()
        db.add(InventorySnapshot(company_id=UUID(company_id), branch_id=branch_id,
            source_upload_id=upload.id, product_id=complete.id,
            business_date=upload.business_date, batch_number="B-1",
            opening_quantity=Decimal("3"), closing_quantity=Decimal("2"),
            unit="g", damaged_quantity=Decimal("0"), wasted_quantity=Decimal("0"),
            adjustment_quantity=Decimal("0")))
        add_inventory_coverage(db, upload, complete)
        add_inventory_coverage(db, upload, no_stock, status="NO_STOCK")
        add_inventory_coverage(db, upload, partial, status="PARTIAL")
        db.commit()
    response = client.get("/api/v1/analytics/inventory/overview?as_of_date=2026-11-25",
        cookies={"stockpilot_session": token})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["coverage_status"] == "INCOMPLETE"
    states = {row["sku"]: row for row in data["ingredient_coverage"]}
    assert states["ING-COMPLETE"]["status"] == "COMPLETE"
    assert states["ING-COMPLETE"]["quantity"] == "2.0000"
    assert states["ING-NOSTOCK"]["status"] == "NO_STOCK"
    assert Decimal(states["ING-NOSTOCK"]["quantity"]) == Decimal("0")
    assert states["ING-UNKNOWN"]["status"] == "UNREPORTED"
    assert states["ING-UNKNOWN"]["quantity"] is None
    assert states["ING-PARTIAL"]["status"] == "PARTIAL"
    assert states["ING-PARTIAL"]["quantity"] is None


def waste_response(client, token, branch_id=None):
    params = "start_date=2026-11-25&end_date=2026-11-25"
    if branch_id is not None:
        params += f"&branch_id={branch_id}"
    return client.get("/api/v1/analytics/waste/overview?" + params,
        cookies={"stockpilot_session": token})


def test_waste_overview_includes_ledger_waste_and_damage(test_environment):
    client, sessions = test_environment
    token, company_id = owner(client, "waste-ledger@example.com", "Waste Ledger")
    branch_id, product_id = seed_base(sessions, company_id)
    with sessions() as db:
        upload = db.scalar(select(DailyUpload).where(
            DailyUpload.branch_id == branch_id, DailyUpload.is_current.is_(True)))
        add_waste_evidence(db, upload.company_id, branch_id, product_id,
            kind="WASTE", quantity="4.25")
        add_waste_evidence(db, upload.company_id, branch_id, product_id,
            kind="DAMAGE", quantity="1.5")
        db.commit()
    response = waste_response(client, token)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["wasted_by_product"][0]["wasted"] == "4.2500"
    assert data["damaged_by_product"][0]["damaged"] == "1.5000"
    assert data["snapshot_ledger_reconciliation"] == "AMBIGUOUS"
    assert data["recorded_value"] is None
    assert data["cost_coverage_complete"] is False


def test_voided_and_unrelated_movements_are_excluded(test_environment):
    client, sessions = test_environment
    token, company_id = owner(client, "waste-filter@example.com", "Waste Filter")
    branch_id, product_id = seed_base(sessions, company_id)
    with sessions() as db:
        snapshot = db.scalar(select(InventorySnapshot))
        snapshot.damaged_quantity = Decimal("0")
        snapshot.wasted_quantity = Decimal("0")
        add_waste_evidence(db, snapshot.company_id, branch_id, product_id,
            kind="WASTE", quantity="9", voided=True)
        add_waste_evidence(db, snapshot.company_id, branch_id, product_id,
            kind="NEGATIVE_ADJUSTMENT", quantity="12")
        db.commit()
    response = waste_response(client, token)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["wasted_by_product"][0]["wasted"] is None
    assert data["damaged_by_product"][0]["damaged"] is None
    assert data["quantity_coverage_status"] == "PARTIAL"


def test_superseded_upload_movements_are_excluded(test_environment):
    client, sessions = test_environment
    token, company_id = owner(client, "waste-old-version@example.com", "Waste Old Version")
    branch_id, product_id = seed_base(sessions, company_id)
    with sessions() as db:
        old_upload = db.scalar(select(DailyUpload).where(
            DailyUpload.branch_id == branch_id, DailyUpload.is_current.is_(True)))
        old_upload.is_current = False
        new_upload = DailyUpload(company_id=old_upload.company_id,
            branch_id=old_upload.branch_id, business_date=old_upload.business_date,
            uploaded_by_membership_id=old_upload.uploaded_by_membership_id,
            object_key="waste-current-version.xlsx", original_filename="replacement.xlsx",
            content_type=old_upload.content_type, file_size_bytes=100,
            version=old_upload.version + 1, status="UPLOADED", is_current=True,
            processing_status="COMPLETED")
        db.add(new_upload)
        add_waste_evidence(db, old_upload.company_id, branch_id, product_id,
            kind="WASTE", quantity="7", origin="UPLOAD", upload=old_upload)
        db.flush()
        snapshot = db.scalar(select(InventorySnapshot))
        snapshot.damaged_quantity = Decimal("0")
        snapshot.wasted_quantity = Decimal("0")
        db.commit()
    response = waste_response(client, token)
    assert response.status_code == 200, response.text
    assert response.json()["wasted_by_product"] == []
    assert response.json()["quantity_coverage_status"] == "UNAVAILABLE"


def test_complete_ledger_coverage_prevents_snapshot_double_count(test_environment):
    client, sessions = test_environment
    token, company_id = owner(client, "waste-overlap@example.com", "Waste Overlap")
    branch_id, product_id = seed_base(sessions, company_id)
    with sessions() as db:
        upload = db.scalar(select(DailyUpload).where(
            DailyUpload.branch_id == branch_id, DailyUpload.is_current.is_(True)))
        snapshot = db.scalar(select(InventorySnapshot))
        snapshot.damaged_quantity = Decimal("1.5")
        snapshot.wasted_quantity = Decimal("4.25")
        add_waste_evidence(db, upload.company_id, branch_id, product_id,
            kind="WASTE", quantity="4.25")
        add_waste_evidence(db, upload.company_id, branch_id, product_id,
            kind="DAMAGE", quantity="1.5")
        add_waste_category_coverage(db, upload, product_id, kind="WASTE")
        add_waste_category_coverage(db, upload, product_id, kind="DAMAGE")
        db.commit()
    data = waste_response(client, token).json()
    assert data["wasted_by_product"][0]["wasted"] == "4.2500"
    assert data["damaged_by_product"][0]["damaged"] == "1.5000"
    assert data["quantity_coverage_status"] == "COMPLETE"
    assert data["snapshot_ledger_reconciliation"] == "LEDGER_AUTHORITATIVE"
    assert data["recorded_value"] is None


def test_complete_ledger_snapshot_conflict_is_reported_as_ambiguous(test_environment):
    client, sessions = test_environment
    token, company_id = owner(client, "waste-conflict@example.com", "Waste Conflict")
    branch_id, product_id = seed_base(sessions, company_id)
    with sessions() as db:
        upload = db.scalar(select(DailyUpload).where(
            DailyUpload.branch_id == branch_id, DailyUpload.is_current.is_(True)))
        add_waste_evidence(db, upload.company_id, branch_id, product_id,
            kind="WASTE", quantity="4")
        add_waste_category_coverage(db, upload, product_id, kind="WASTE")
        add_waste_category_coverage(db, upload, product_id, kind="DAMAGE")
        db.commit()
    data = waste_response(client, token).json()
    assert data["wasted_by_product"][0]["wasted"] is None
    assert data["quantity_coverage_status"] == "PARTIAL"
    assert data["snapshot_ledger_reconciliation"] == "AMBIGUOUS"


def test_unreported_snapshot_zero_is_not_reported_as_confirmed_zero(test_environment):
    client, sessions = test_environment
    token, company_id = owner(client, "waste-unknown-zero@example.com", "Waste Unknown Zero")
    seed_base(sessions, company_id)
    with sessions() as db:
        snapshot = db.scalar(select(InventorySnapshot))
        snapshot.damaged_quantity = Decimal("0")
        snapshot.wasted_quantity = Decimal("0")
        db.commit()
    response = waste_response(client, token)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["wasted_by_product"][0]["damaged"] is None
    assert data["wasted_by_product"][0]["wasted"] is None
    assert data["recorded_value"] is None
    assert data["quantity_coverage_status"] == "PARTIAL"


def test_waste_totals_are_scoped_and_company_aggregations_do_not_double_count(test_environment):
    client, sessions = test_environment
    token, company_id = owner(client, "waste-branches@example.com", "Waste Branches")
    branch_a_id, product_id = seed_base(sessions, company_id)
    branch_b_response = client.post("/api/v1/branches", cookies={
        "stockpilot_session": token}, json={"name": "East", "code": "EAS",
        "country_code": "IN", "timezone": "Asia/Kolkata"})
    assert branch_b_response.status_code == 201
    branch_b_id = UUID(branch_b_response.json()["id"])
    with sessions() as db:
        upload_a = db.scalar(select(DailyUpload).where(
            DailyUpload.branch_id == branch_a_id, DailyUpload.is_current.is_(True)))
        membership = db.scalar(select(CompanyMembership).where(
            CompanyMembership.company_id == upload_a.company_id))
        upload_b = DailyUpload(company_id=upload_a.company_id, branch_id=branch_b_id,
            business_date=upload_a.business_date,
            uploaded_by_membership_id=membership.id, object_key="waste-east.xlsx",
            original_filename="east.xlsx", content_type=upload_a.content_type,
            file_size_bytes=100, version=1, status="UPLOADED", is_current=True,
            processing_status="COMPLETED")
        db.add(upload_b)
        db.flush()
        for upload in (upload_a, upload_b):
            add_waste_category_coverage(db, upload, product_id, kind="WASTE")
            add_waste_category_coverage(db, upload, product_id, kind="DAMAGE")
        add_waste_evidence(db, upload_a.company_id, branch_a_id, product_id,
            kind="WASTE", quantity="2")
        add_waste_evidence(db, upload_b.company_id, branch_b_id, product_id,
            kind="WASTE", quantity="5")
        db.commit()
    company_data = waste_response(client, token).json()
    assert len(company_data["by_branch"]) == 2
    assert sum(Decimal(row["wasted"]) for row in company_data["by_branch"]) == Decimal("7")
    assert company_data["wasted_by_product"][0]["wasted"] == "7.0000"
    branch_data = waste_response(client, token, branch_a_id).json()
    assert len(branch_data["by_branch"]) == 1
    assert branch_data["by_branch"][0]["wasted"] == "2.0000"
