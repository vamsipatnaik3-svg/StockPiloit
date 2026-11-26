from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select

from app.core.branch_scope import BranchAccessScope
from app.models import Branch, CompanyMembership, Product, User
from app.services.variance_intelligence import variance_intelligence as _variance_intelligence
from app.services.variance_rules import (BASELINE_PERIODS, MIN_ABSOLUTE_VARIANCE,
    MIN_BASELINE_PERIODS, MIN_OPERATIONAL_RATE_POINT_CHANGE)


def variance_intelligence(db, company_id, start_date, end_date, branch_id=None,
        ingredient_id=None, *args, **kwargs):
    # Pure calculator tests replace the database loader and provide an explicit
    # synthetic scope; HTTP integration tests exercise DB-backed resolution.
    kwargs.setdefault("branch_scope", BranchAccessScope(
        company_id=company_id, membership_id=uuid4(), role="OWNER",
        branch_ids=frozenset({branch_id or uuid4()}), scope_type="COMPANY"))
    return _variance_intelligence(db, company_id, start_date, end_date,
        branch_id, ingredient_id, *args, **kwargs)


def _row(company, branch, ingredient, value, *, status="COMPLETE", theory_status="COMPLETE",
         movements=None, denominator="0", variance_percent=None):
    item = {"branch_id": branch, "ingredient_id": ingredient, "company_id": company,
        "branch_name": "Central", "ingredient_sku": "ING-1", "ingredient_name": "Coffee",
        "canonical_unit": "g", "status": status, "theoretical_status": theory_status,
        "comparison_status": "COMPLETE" if status == theory_status == "COMPLETE" else status,
        "absolute_variance": Decimal(value), "actual_sales_related_consumption": Decimal("20"),
        "theoretical_consumption": Decimal("20") - Decimal(value), "variance_percent": variance_percent,
        "reason_codes": [], "theoretical_reason_codes": []}
    movement_values = {"WASTE": Decimal(0), "DAMAGE": Decimal(0),
        "STAFF_CONSUMPTION": Decimal(0), "POSITIVE_ADJUSTMENT": Decimal(0),
        "NEGATIVE_ADJUSTMENT": Decimal(0), "OTHER_OUTFLOW": Decimal(0), "TRANSFER_OUT": Decimal(0)}
    movement_values.update(movements or {})
    return {"item": item, "movements": movement_values,
        "outflow_denominator": Decimal(denominator), "adjustment_count": 0,
        "positive_adjustment_count": 0, "negative_adjustment_count": 0, "reason_codes": []}


def _expected_comparison_periods(current_start, count=BASELINE_PERIODS, period_days=1):
    period_stride = ((period_days + 6) // 7) * 7
    periods = []
    for index in range(count):
        end = current_start - timedelta(days=index * period_stride + 1)
        begin = end - timedelta(days=period_days - 1)
        periods.append({"start_date": begin, "end_date": end})
    return periods


def test_materiality_defaults_are_centralized():
    assert MIN_ABSOLUTE_VARIANCE == Decimal("1")
    assert MIN_OPERATIONAL_RATE_POINT_CHANGE == Decimal("5")


def test_variance_anomaly_baseline_and_identifier_are_deterministic(monkeypatch):
    company, branch, ingredient = uuid4(), uuid4(), uuid4()
    report_day = date(2026, 11, 25)

    def fake_period(db, company_id, start, end, branch_id, ingredient_id, branch_scope):
        value = "20" if start == report_day else "5"
        return {}, {}, {(branch, ingredient): _row(company, branch, ingredient, value)}

    monkeypatch.setattr("app.services.variance_intelligence._period_data", fake_period)
    first = variance_intelligence(object(), company, report_day, report_day,
        branch, ingredient)
    second = variance_intelligence(object(), company, report_day, report_day,
        branch, ingredient)
    variance = next(item for item in first["findings"] if item["finding_type"] == "CONSUMPTION_VARIANCE")
    assert variance["status"] == "ANOMALY"
    assert variance["metric_value"] == Decimal("20")
    assert variance["baseline_value"] == Decimal("5")
    assert variance["confidence"] == "HIGH"
    assert variance["severity"] == "LOW"  # Large one-period deviation; no persistence evidence.
    assert variance["id"] == next(item for item in second["findings"]
        if item["finding_type"] == "CONSUMPTION_VARIANCE")["id"]
    assert variance["recommendation"]
    assert variance["baseline_comparison_periods"] == _expected_comparison_periods(report_day)
    assert variance["start_date"] == variance["end_date"] == report_day
    assert all(period["end_date"] < variance["start_date"]
        for period in variance["baseline_comparison_periods"])
    assert {"id", "finding_type", "status", "baseline_periods", "baseline_value",
        "start_date", "end_date", "evidence", "explanation"}.issubset(variance)


def test_insufficient_baseline_explanation_and_dates_are_accurate(monkeypatch):
    company, branch, ingredient = uuid4(), uuid4(), uuid4()
    report_day = date(2026, 11, 25)
    windows = _expected_comparison_periods(report_day)

    def fake_period(db, company_id, start, end, branch_id, ingredient_id, branch_scope):
        if start == report_day:
            return {}, {}, {(branch, ingredient): _row(company, branch, ingredient, "20")}
        index = next(i for i, window in enumerate(windows) if window["start_date"] == start)
        status = "COMPLETE" if index < MIN_BASELINE_PERIODS - 1 else "INCOMPLETE"
        return {}, {}, {(branch, ingredient): _row(company, branch, ingredient, "5",
            status=status, theory_status="COMPLETE")}

    monkeypatch.setattr("app.services.variance_intelligence._period_data", fake_period)
    result = variance_intelligence(object(), company, report_day, report_day,
        branch, ingredient)
    finding = next(item for item in result["findings"]
        if item["finding_type"] == "CONSUMPTION_VARIANCE")

    assert finding["status"] == "INSUFFICIENT_BASELINE"
    assert finding["baseline_periods"] == MIN_BASELINE_PERIODS - 1
    assert finding["baseline_value"] is None
    assert finding["baseline_comparison_periods"] == []
    assert "Fewer than four complete, metric-eligible" in finding["explanation"]
    assert "marked insufficient baseline" in finding["explanation"]


def test_exactly_four_eligible_periods_form_baseline(monkeypatch):
    company, branch, ingredient = uuid4(), uuid4(), uuid4()
    report_day = date(2026, 11, 25)
    windows = _expected_comparison_periods(report_day)

    def fake_period(db, company_id, start, end, branch_id, ingredient_id, branch_scope):
        if start == report_day:
            return {}, {}, {(branch, ingredient): _row(company, branch, ingredient, "20")}
        index = next(i for i, window in enumerate(windows) if window["start_date"] == start)
        status = "COMPLETE" if index < MIN_BASELINE_PERIODS else "INCOMPLETE"
        return {}, {}, {(branch, ingredient): _row(company, branch, ingredient, "5",
            status=status, theory_status="COMPLETE")}

    monkeypatch.setattr("app.services.variance_intelligence._period_data", fake_period)
    result = variance_intelligence(object(), company, report_day, report_day,
        branch, ingredient)
    finding = next(item for item in result["findings"]
        if item["finding_type"] == "CONSUMPTION_VARIANCE")

    assert finding["baseline_periods"] == MIN_BASELINE_PERIODS
    assert finding["baseline_value"] == Decimal("5")
    assert finding["baseline_comparison_periods"] == windows[:MIN_BASELINE_PERIODS]
    assert finding["confidence"] == "MEDIUM"


def test_more_than_four_periods_report_exact_eligible_windows_only(monkeypatch):
    company, branch, ingredient = uuid4(), uuid4(), uuid4()
    report_day = date(2026, 11, 25)
    windows = _expected_comparison_periods(report_day)
    eligible_indexes = {0, 1, 3, 4, 6, 7}

    def fake_period(db, company_id, start, end, branch_id, ingredient_id, branch_scope):
        if start == report_day:
            return {}, {}, {(branch, ingredient): _row(company, branch, ingredient, "20")}
        index = next(i for i, window in enumerate(windows) if window["start_date"] == start)
        status = "COMPLETE" if index in eligible_indexes else "INCOMPLETE"
        return {}, {}, {(branch, ingredient): _row(company, branch, ingredient,
            str(5 + index), status=status, theory_status="COMPLETE")}

    monkeypatch.setattr("app.services.variance_intelligence._period_data", fake_period)
    result = variance_intelligence(object(), company, report_day, report_day,
        branch, ingredient)
    finding = next(item for item in result["findings"]
        if item["finding_type"] == "CONSUMPTION_VARIANCE")
    expected = [window for index, window in enumerate(windows)
        if index in eligible_indexes]

    assert finding["baseline_periods"] == 6
    assert finding["baseline_comparison_periods"] == expected
    assert finding["start_date"] == finding["end_date"] == report_day
    assert all(period not in finding["baseline_comparison_periods"]
        for index, period in enumerate(windows) if index not in eligible_indexes)


def test_findings_without_usable_baseline_have_empty_period_list(monkeypatch):
    company, branch, ingredient = uuid4(), uuid4(), uuid4()
    report_day = date(2026, 11, 25)

    def fake_period(db, company_id, start, end, branch_id, ingredient_id, branch_scope):
        return {}, {}, {(branch, ingredient): _row(company, branch, ingredient, "20",
            status="INCOMPLETE", theory_status="INCOMPLETE")}

    monkeypatch.setattr("app.services.variance_intelligence._period_data", fake_period)
    result = variance_intelligence(object(), company, report_day, report_day,
        branch, ingredient)
    assert all(finding["baseline_comparison_periods"] == []
        for finding in result["findings"])


def test_variance_current_and_historical_queries_share_the_same_scope(monkeypatch):
    company, branch, ingredient = uuid4(), uuid4(), uuid4()
    report_day = date(2026, 11, 25)
    scope = BranchAccessScope(company_id=company, membership_id=uuid4(), role="MANAGER",
        branch_ids=frozenset({branch}), scope_type="BRANCH_SET")
    seen_scopes = []

    def fake_period(db, company_id, start, end, branch_id, ingredient_id, resolved_scope):
        seen_scopes.append(resolved_scope)
        return {}, {}, {(branch, ingredient): _row(company, branch, ingredient, "2")}

    monkeypatch.setattr("app.services.variance_intelligence._period_data", fake_period)
    _variance_intelligence(object(), company, report_day, report_day, branch,
        ingredient, branch_scope=scope)
    assert len(seen_scopes) == BASELINE_PERIODS + 1
    assert all(resolved is scope for resolved in seen_scopes)


def test_incomplete_data_never_becomes_operational_anomaly(monkeypatch):
    company, branch, ingredient = uuid4(), uuid4(), uuid4()
    report_day = date(2026, 11, 25)

    def fake_period(db, company_id, start, end, branch_id, ingredient_id, branch_scope):
        return {}, {}, {(branch, ingredient): _row(company, branch, ingredient, "20",
            status="INCOMPLETE", theory_status="COMPLETE")}

    monkeypatch.setattr("app.services.variance_intelligence._period_data", fake_period)
    result = variance_intelligence(object(), company, report_day, report_day,
        branch, ingredient)
    assert all(item["finding_type"] == "DATA_QUALITY" for item in result["findings"])
    assert result["findings"][0]["status"] == "INCOMPLETE_DATA"
    assert result["findings"][0]["severity"] is None


def test_zero_theoretical_variance_has_no_percent_inference(monkeypatch):
    company, branch, ingredient = uuid4(), uuid4(), uuid4()
    report_day = date(2026, 11, 25)

    def fake_period(db, company_id, start, end, branch_id, ingredient_id, branch_scope):
        row = _row(company, branch, ingredient, "5")
        if start == report_day:
            row["item"]["theoretical_consumption"] = Decimal(0)
            row["item"]["variance_percent"] = None
        return {}, {}, {(branch, ingredient): row}

    monkeypatch.setattr("app.services.variance_intelligence._period_data", fake_period)
    result = variance_intelligence(object(), company, report_day, report_day,
        branch, ingredient)
    finding = next(item for item in result["findings"] if item["finding_type"] == "CONSUMPTION_VARIANCE")
    assert finding["evidence"]["variance_percent"] is None
    assert finding["percentage_difference"] is not None  # Baseline delta is separate from theoretical denominator.


def test_negative_variance_reports_below_theoretical_direction(monkeypatch):
    company, branch, ingredient = uuid4(), uuid4(), uuid4()
    report_day = date(2026, 11, 25)

    def fake_period(db, company_id, start, end, branch_id, ingredient_id, branch_scope):
        value = "-20" if start == report_day else "-5"
        return {}, {}, {(branch, ingredient): _row(company, branch, ingredient, value)}

    monkeypatch.setattr("app.services.variance_intelligence._period_data", fake_period)
    result = variance_intelligence(object(), company, report_day, report_day, branch, ingredient)
    finding = next(item for item in result["findings"] if item["finding_type"] == "CONSUMPTION_VARIANCE")
    assert finding["direction"] == "BELOW_THEORETICAL"
    assert finding["status"] == "ANOMALY"


def test_waste_rate_is_omitted_when_current_outflow_denominator_is_zero(monkeypatch):
    company, branch, ingredient = uuid4(), uuid4(), uuid4()
    report_day = date(2026, 11, 25)

    def fake_period(db, company_id, start, end, branch_id, ingredient_id, branch_scope):
        row = _row(company, branch, ingredient, "0", movements={"WASTE": Decimal("2")}, denominator="10")
        if start == report_day:
            row = _row(company, branch, ingredient, "0", movements={"WASTE": Decimal("2")}, denominator="0")
        return {}, {}, {(branch, ingredient): row}

    monkeypatch.setattr("app.services.variance_intelligence._period_data", fake_period)
    result = variance_intelligence(object(), company, report_day, report_day, branch, ingredient)
    assert not any(item["finding_type"] == "WASTE_RATE" for item in result["findings"])


def test_positive_and_negative_adjustments_are_separate(monkeypatch):
    company, branch, ingredient = uuid4(), uuid4(), uuid4()
    report_day = date(2026, 11, 25)

    def fake_period(db, company_id, start, end, branch_id, ingredient_id, branch_scope):
        current = start == report_day
        row = _row(company, branch, ingredient, "0", movements={
            "POSITIVE_ADJUSTMENT": Decimal("8" if current else "0"),
            "NEGATIVE_ADJUSTMENT": Decimal("3" if current else "0")})
        row["positive_adjustment_count"] = 2 if current else 0
        row["negative_adjustment_count"] = 1 if current else 0
        row["adjustment_count"] = row["positive_adjustment_count"] + row["negative_adjustment_count"]
        row["reason_codes"] = ["POSITIVE_COUNT_CORRECTION", "NEGATIVE_COUNT_CORRECTION"]
        return {}, {}, {(branch, ingredient): row}

    monkeypatch.setattr("app.services.variance_intelligence._period_data", fake_period)
    result = variance_intelligence(object(), company, report_day, report_day, branch, ingredient)
    anomaly_types = {item["finding_type"] for item in result["findings"] if item["status"] == "ANOMALY"}
    assert "POSITIVE_ADJUSTMENT" in anomaly_types
    assert "NEGATIVE_ADJUSTMENT" in anomaly_types


def test_branch_waste_comparison_requires_three_complete_peers(monkeypatch):
    company, ingredient = uuid4(), uuid4()
    branches = [uuid4(), uuid4(), uuid4()]
    report_day = date(2026, 11, 25)

    def fake_period(db, company_id, start, end, branch_id, ingredient_id, branch_scope):
        rows = {}
        for index, branch in enumerate(branches):
            waste = "20" if index == 0 else "5"
            rows[(branch, ingredient)] = _row(company, branch, ingredient, "0",
                movements={"WASTE": Decimal(waste)}, denominator="100")
        return {}, {}, rows

    monkeypatch.setattr("app.services.variance_intelligence._period_data", fake_period)
    result = variance_intelligence(object(), company, report_day, report_day)
    peer = [item for item in result["findings"] if item["finding_type"] == "BRANCH_WASTE_RATE"]
    assert len(peer) == 1
    assert peer[0]["branch_id"] == branches[0]


def test_owner_endpoint_tenant_filter_and_pagination(test_environment):
    client, sessions = test_environment
    def create_owner(email):
        registered = client.post("/api/v1/auth/register", json={
            "full_name": "Variance Owner", "email": email, "password": "StockPilot_Test_123!",
            "company_name": "Variance Cafe", "industry": "CAFE", "country_code": "IN",
            "currency": "INR", "timezone": "Asia/Kolkata"})
        assert registered.status_code == 201, registered.text
        company = UUID(registered.json()["company_id"])
        logged = client.post("/api/v1/auth/login", json={"email": email,
            "password": "StockPilot_Test_123!"})
        assert logged.status_code == 200
        token = logged.cookies.get("stockpilot_session")
        with sessions() as db:
            membership = db.scalar(select(CompanyMembership).join(User).where(User.email == email))
            branch = Branch(company_id=company, name="Variance Branch", code="VAR",
                country_code="IN", timezone="Asia/Kolkata")
            ingredient = Product(company_id=company, sku="ING-VAR", product_name="Coffee",
                unit_of_measure="g", product_kind="INGREDIENT")
            db.add_all([branch, ingredient])
            db.commit()
            return {"token": token, "ingredient_id": ingredient.id}
    first = create_owner("variance-one@example.com")
    second = create_owner("variance-two@example.com")
    params = "start_date=2026-11-25&end_date=2026-11-25&finding_type=DATA_QUALITY&limit=1"
    response = client.get("/api/v1/analytics/variance/intelligence?" + params,
        cookies={"stockpilot_session": first["token"]})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total"] >= 1
    assert len(payload["findings"]) == 1
    assert payload["findings"][0]["status"] in {"INCOMPLETE_DATA", "UNAVAILABLE"}
    assert payload["findings"][0]["baseline_comparison_periods"] == []
    next_page = client.get("/api/v1/analytics/variance/intelligence?" + params
        + "&offset=1", cookies={"stockpilot_session": first["token"]})
    assert next_page.status_code == 200, next_page.text
    assert next_page.json()["total"] == payload["total"]
    assert next_page.json()["offset"] == 1
    assert len(next_page.json()["findings"]) <= 1
    assert not ({item["id"] for item in payload["findings"]}
        & {item["id"] for item in next_page.json()["findings"]})
    foreign = client.get("/api/v1/analytics/variance/intelligence?" + params
        + "&ingredient_id=" + str(second["ingredient_id"]),
        cookies={"stockpilot_session": first["token"]})
    assert foreign.status_code == 404

