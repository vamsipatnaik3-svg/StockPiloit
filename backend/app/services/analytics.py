from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from app.core.branch_scope import BranchAccessScope
from app.models import (Branch, Company, CompanyMembership, DailyUpload,
    InventorySnapshot, Product, ProductCategory, PurchaseLine, SalesRecord,
    StockCoverageDeclaration, StockMovement, UploadValidationIssue)

ZERO = Decimal("0")


@dataclass(frozen=True)
class AnalyticsPeriod:
    start: date
    end: date
    previous_start: date
    previous_end: date

    def as_dict(self) -> dict:
        return {"start_date": self.start, "end_date": self.end,
            "previous_start_date": self.previous_start,
            "previous_end_date": self.previous_end}


def resolve_period(start_date: date | None, end_date: date | None) -> AnalyticsPeriod:
    end = end_date or date.today()
    start = start_date or end - timedelta(days=29)
    if start > end:
        raise HTTPException(status_code=422, detail="start_date must be on or before end_date.")
    if (end - start).days > 3660:
        raise HTTPException(status_code=422, detail="Date range cannot exceed 10 years.")
    duration = end - start + timedelta(days=1)
    return AnalyticsPeriod(start, end, start - duration, start - timedelta(days=1))


def validate_branch(db: Session, membership: CompanyMembership, branch_id: UUID | None) -> None:
    if branch_id is None:
        return
    branch = db.scalar(select(Branch.id).where(
        Branch.id == branch_id, Branch.company_id == membership.company_id
    ))
    if branch is None:
        raise HTTPException(status_code=404, detail="Branch not found.")


def _metric(current: Decimal | int | None, previous: Decimal | int | None) -> dict:
    change = None
    if current is not None and previous is not None and previous != 0:
        change = ((Decimal(current) - Decimal(previous)) / abs(Decimal(previous)) * 100).quantize(Decimal("0.01"))
    return {"current": current, "previous": previous, "change_percent": change}


def _purchase_spend_result(total_lines: int, priced_lines: int,
                           known_spend: Decimal | None,
                           missing_receipt_dates: int) -> tuple[Decimal | None, str]:
    if missing_receipt_dates:
        return None, "PARTIAL"
    spend = (known_spend if total_lines and total_lines == priced_lines
        else ZERO if total_lines == 0 else None)
    return spend, "COMPLETE"


def _sales_filters(company_id: UUID, start: date, end: date,
                   branch_id: UUID | None, scope: BranchAccessScope):
    if scope.company_id != company_id:
        raise ValueError("Analytics scope company does not match query company.")
    filters = [SalesRecord.company_id == company_id,
        SalesRecord.business_date >= start, SalesRecord.business_date <= end,
        DailyUpload.company_id == company_id,
        DailyUpload.branch_id == SalesRecord.branch_id,
        DailyUpload.business_date == SalesRecord.business_date,
        DailyUpload.is_current.is_(True),
        DailyUpload.processing_status == "COMPLETED"]
    filters.extend(scope.criteria(SalesRecord.company_id, SalesRecord.branch_id))
    return filters


def _sales_summary(db: Session, company_id: UUID, start: date, end: date,
                   branch_id: UUID | None, scope: BranchAccessScope) -> dict:
    filters = _sales_filters(company_id, start, end, branch_id, scope)
    revenue, lines, days = db.execute(select(
        func.sum(SalesRecord.net_amount), func.count(SalesRecord.id),
        func.count(func.distinct(SalesRecord.business_date)),
    ).join(DailyUpload, DailyUpload.id == SalesRecord.source_upload_id).where(*filters)).one()
    transaction_groups = select(
        SalesRecord.branch_id, SalesRecord.business_date, SalesRecord.transaction_id
    ).join(DailyUpload, DailyUpload.id == SalesRecord.source_upload_id).where(
        *filters, SalesRecord.granularity == "TRANSACTION",
        SalesRecord.transaction_id.is_not(None),
    ).group_by(SalesRecord.branch_id, SalesRecord.business_date, SalesRecord.transaction_id).subquery()
    transaction_count = db.scalar(select(func.count()).select_from(transaction_groups)) or 0
    transaction_rows, aggregated_rows = db.execute(select(
        func.sum(case((SalesRecord.granularity == "TRANSACTION", 1), else_=0)),
        func.sum(case((SalesRecord.granularity == "AGGREGATED", 1), else_=0)),
    ).join(DailyUpload, DailyUpload.id == SalesRecord.source_upload_id).where(*filters)).one()
    transaction_rows = transaction_rows or 0
    aggregated_rows = aggregated_rows or 0
    transaction_coverage = (
        "UNAVAILABLE" if not transaction_rows else
        "PARTIAL" if aggregated_rows else "COMPLETE"
    )
    return {"revenue": revenue, "lines": lines or 0, "days": days or 0,
        "transactions": transaction_count if transaction_rows else None,
        "transaction_coverage": transaction_coverage}


def _sales_coverage(db: Session, company_id: UUID, start: date, end: date,
                    scope: BranchAccessScope) -> dict:
    """Describe upload presence for each authorized branch/calendar-date pair.

    There is no operating-day calendar. A missing upload is reported as missing
    evidence, never as a zero-sales or closed-day assertion.
    """
    branches = db.execute(select(Branch.id, Branch.name).where(
        Branch.company_id == company_id,
        *scope.criteria(Branch.company_id, Branch.id),
    ).order_by(Branch.name, Branch.id)).all()
    branch_ids = [row.id for row in branches]
    if not branch_ids:
        return {"status": "UNAVAILABLE",
            "basis": "Inclusive calendar dates; no operating-day calendar is configured.",
            "evaluated_branch_days": 0, "sales_available_branch_days": 0,
            "confirmed_zero_sales_branch_days": 0, "missing_upload_branch_days": 0,
            "incomplete_upload_branch_days": 0, "branches": []}

    uploads = db.scalars(select(DailyUpload).where(
        DailyUpload.company_id == company_id,
        DailyUpload.branch_id.in_(branch_ids),
        DailyUpload.business_date >= start,
        DailyUpload.business_date <= end,
    )).all()
    uploads_by_day: dict[tuple[UUID, date], list[DailyUpload]] = {}
    for upload in uploads:
        uploads_by_day.setdefault((upload.branch_id, upload.business_date), []).append(upload)
    completed = {key: [upload for upload in versions
        if upload.is_current and upload.processing_status == "COMPLETED"]
        for key, versions in uploads_by_day.items()}
    completed_ids = [upload.id for versions in completed.values() for upload in versions]
    sales_counts: dict[UUID, int] = {}
    if completed_ids:
        sales_counts = dict(db.execute(select(SalesRecord.source_upload_id,
            func.count(SalesRecord.id)).where(
                SalesRecord.company_id == company_id,
                SalesRecord.source_upload_id.in_(completed_ids),
            ).group_by(SalesRecord.source_upload_id)).all())

    dates = tuple(start + timedelta(days=offset)
        for offset in range((end - start).days + 1))
    branches_out = []
    totals = {"SALES_AVAILABLE": 0, "CONFIRMED_ZERO": 0,
        "MISSING_UPLOAD": 0, "INCOMPLETE": 0}
    for branch in branches:
        available = zero = 0
        missing_dates: list[date] = []
        incomplete_dates: list[date] = []
        for business_date in dates:
            key = (branch.id, business_date)
            versions = uploads_by_day.get(key, [])
            current = completed.get(key, [])
            if len(current) == 1:
                if sales_counts.get(current[0].id, 0):
                    available += 1
                    totals["SALES_AVAILABLE"] += 1
                else:
                    zero += 1
                    totals["CONFIRMED_ZERO"] += 1
            elif versions:
                incomplete_dates.append(business_date)
                totals["INCOMPLETE"] += 1
            else:
                missing_dates.append(business_date)
                totals["MISSING_UPLOAD"] += 1
        branch_status = "INCOMPLETE" if missing_dates or incomplete_dates else "COMPLETE"
        branches_out.append({"branch_id": branch.id, "branch_name": branch.name,
            "status": branch_status, "sales_available_days": available,
            "confirmed_zero_sales_days": zero,
            "missing_upload_dates": missing_dates,
            "incomplete_upload_dates": incomplete_dates})

    evaluated = len(branches) * len(dates)
    return {"status": "COMPLETE" if totals["MISSING_UPLOAD"] == 0
            and totals["INCOMPLETE"] == 0 else "INCOMPLETE",
        "basis": "Inclusive calendar dates; no operating-day calendar is configured. "
            "CONFIRMED_ZERO means a current completed workbook contained no sales rows.",
        "evaluated_branch_days": evaluated,
        "sales_available_branch_days": totals["SALES_AVAILABLE"],
        "confirmed_zero_sales_branch_days": totals["CONFIRMED_ZERO"],
        "missing_upload_branch_days": totals["MISSING_UPLOAD"],
        "incomplete_upload_branch_days": totals["INCOMPLETE"],
        "branches": branches_out}


def _overview_waste_values(waste_report: dict) -> tuple[Decimal | None, str | None, list[dict]]:
    """Build the legacy combined waste+damage KPI from reconciled unit rows."""
    by_unit: dict[str, dict] = {}
    for row in waste_report["by_unit"]:
        unit = row["unit"]
        bucket = by_unit.setdefault(unit, {"damaged": ZERO, "wasted": ZERO,
            "damaged_known": True, "wasted_known": True,
            "damaged_status": "COMPLETE", "wasted_status": "COMPLETE"})
        for kind in ("damaged", "wasted"):
            status = row[f"{kind}_coverage_status"]
            value = row[kind]
            if value is None:
                bucket[f"{kind}_known"] = False
            else:
                bucket[kind] += value
            if status != "COMPLETE":
                bucket[f"{kind}_status"] = status

    result = []
    for unit, bucket in sorted(by_unit.items()):
        complete = (bucket["damaged_known"] and bucket["wasted_known"]
            and bucket["damaged_status"] == "COMPLETE"
            and bucket["wasted_status"] == "COMPLETE")
        quantity = bucket["damaged"] + bucket["wasted"] if complete else None
        result.append({"unit": unit, "quantity": quantity,
            "damaged": bucket["damaged"] if bucket["damaged_known"] else None,
            "wasted": bucket["wasted"] if bucket["wasted_known"] else None,
            "coverage_status": "COMPLETE" if complete else
                "PARTIAL" if quantity is not None or bucket["damaged_known"]
                    or bucket["wasted_known"] else "UNAVAILABLE"})
    if not result:
        return None, None, result
    if len(result) != 1 or result[0]["coverage_status"] != "COMPLETE":
        return None, result[0]["unit"] if len(result) == 1 else None, result
    return result[0]["quantity"], result[0]["unit"], result


def _inventory_period_query(company_id: UUID, start: date, end: date,
                            branch_id: UUID | None, scope: BranchAccessScope):
    filters = [InventorySnapshot.company_id == company_id,
        InventorySnapshot.business_date >= start,
        InventorySnapshot.business_date <= end,
        DailyUpload.company_id == company_id,
        DailyUpload.branch_id == InventorySnapshot.branch_id,
        DailyUpload.business_date == InventorySnapshot.business_date,
        DailyUpload.is_current.is_(True),
        DailyUpload.processing_status == "COMPLETED"]
    filters.extend(scope.criteria(InventorySnapshot.company_id,
        InventorySnapshot.branch_id))
    return select(InventorySnapshot).join(
        DailyUpload, DailyUpload.id == InventorySnapshot.source_upload_id
    ).where(*filters)


def overview(db: Session, membership: CompanyMembership, period: AnalyticsPeriod,
             branch_id: UUID | None, scope: BranchAccessScope) -> dict:
    company = db.get(Company, membership.company_id)
    current = _sales_summary(db, membership.company_id, period.start, period.end, branch_id, scope)
    previous = _sales_summary(db, membership.company_id, period.previous_start, period.previous_end, branch_id, scope)
    branch_query = select(func.count(Branch.id)).where(
        Branch.company_id == membership.company_id, Branch.is_active.is_(True))
    branch_query = branch_query.where(*scope.criteria(Branch.company_id, Branch.id))
    active_branches = db.scalar(branch_query) or 0

    reconciled_waste = waste_overview(db, membership, period, branch_id, scope)
    previous_waste = waste_overview(db, membership,
        AnalyticsPeriod(period.previous_start, period.previous_end,
            period.previous_start, period.previous_end), branch_id, scope)
    waste_quantity, waste_unit, waste_by_unit = _overview_waste_values(reconciled_waste)
    waste_value_metric = reconciled_waste["recorded_value"]
    transaction_metric = _metric(current["transactions"], previous["transactions"])
    if (current["transaction_coverage"] != "COMPLETE" or
            previous["transaction_coverage"] != "COMPLETE"):
        transaction_metric["change_percent"] = None

    latest_sales_date = db.scalar(select(func.max(SalesRecord.business_date)).join(
        DailyUpload, DailyUpload.id == SalesRecord.source_upload_id
    ).where(*_sales_filters(membership.company_id, period.start, period.end, branch_id, scope)))
    latest_upload = db.scalar(select(func.max(DailyUpload.business_date)).where(
        DailyUpload.company_id == membership.company_id,
        DailyUpload.is_current.is_(True), DailyUpload.processing_status == "COMPLETED",
        DailyUpload.business_date <= period.end,
        *scope.criteria(DailyUpload.company_id, DailyUpload.branch_id),
    ))
    return {"currency": company.currency, "period": period.as_dict(), "branch_id": branch_id,
        "revenue": _metric(current["revenue"], previous["revenue"]),
        "transaction_count": transaction_metric,
        "transaction_count_coverage": {
            "current": current["transaction_coverage"],
            "previous": previous["transaction_coverage"],
        },
        "sales_coverage": _sales_coverage(db, membership.company_id,
            period.start, period.end, scope),
        "active_branches": active_branches,
        "waste_quantity": waste_quantity, "waste_unit": waste_unit,
        "waste_by_unit": waste_by_unit,
        "waste_value": _metric(waste_value_metric, previous_waste["recorded_value"]),
        "waste_coverage_status": reconciled_waste["quantity_coverage_status"],
        "coverage": {"sales_lines": current["lines"], "sales_days": current["days"],
            "latest_sales_date": latest_sales_date, "latest_upload_date": latest_upload},
        "unsupported_metrics": ["Gross profit: no configured costing method.",
            "Low stock: no product-level thresholds are configured.",
            "Stock turnover: compatible opening/closing quantity history is not sufficient for this calculation."]}


def sales_trends(db: Session, membership: CompanyMembership, period: AnalyticsPeriod,
                 branch_id: UUID | None, scope: BranchAccessScope) -> dict:
    company = db.get(Company, membership.company_id)
    rows = db.execute(select(SalesRecord.business_date, func.sum(SalesRecord.net_amount)).join(
        DailyUpload, DailyUpload.id == SalesRecord.source_upload_id
    ).where(*_sales_filters(membership.company_id, period.start, period.end, branch_id, scope))
    .group_by(SalesRecord.business_date).order_by(SalesRecord.business_date)).all()
    span = (period.end - period.start).days + 1
    grain = "daily" if span <= 45 else "weekly" if span <= 180 else "monthly"
    grouped: dict[date, Decimal] = {}
    for business_date, revenue in rows:
        if grain == "weekly":
            bucket = business_date - timedelta(days=business_date.weekday())
        elif grain == "monthly":
            bucket = business_date.replace(day=1)
        else:
            bucket = business_date
        grouped[bucket] = grouped.get(bucket, ZERO) + revenue
    current = _sales_summary(db, membership.company_id, period.start, period.end, branch_id, scope)["revenue"]
    previous = _sales_summary(db, membership.company_id, period.previous_start, period.previous_end, branch_id, scope)["revenue"]
    comparison = _metric(current, previous)
    return {"currency": company.currency, "grain": grain, "period": period.as_dict(),
        "current_revenue": current, "previous_revenue": previous,
        "change_percent": comparison["change_percent"],
        "points": [{"period_start": bucket, "revenue": value} for bucket, value in sorted(grouped.items())]}


def branch_performance(db: Session, membership: CompanyMembership,
                       period: AnalyticsPeriod, branch_id: UUID | None,
                       scope: BranchAccessScope) -> dict:
    company = db.get(Company, membership.company_id)
    filters = _sales_filters(membership.company_id, period.start, period.end, branch_id, scope)
    rows = db.execute(select(Branch.id, Branch.name, func.sum(SalesRecord.net_amount),
        func.count(SalesRecord.id)).join(SalesRecord, SalesRecord.branch_id == Branch.id)
        .join(DailyUpload, DailyUpload.id == SalesRecord.source_upload_id)
        .where(Branch.company_id == membership.company_id, *filters)
        .group_by(Branch.id, Branch.name).order_by(func.sum(SalesRecord.net_amount).desc())).all()
    transaction_groups = select(SalesRecord.branch_id, SalesRecord.business_date,
        SalesRecord.transaction_id).join(DailyUpload,
        DailyUpload.id == SalesRecord.source_upload_id).where(
        *filters, SalesRecord.granularity == "TRANSACTION",
        SalesRecord.transaction_id.is_not(None)).group_by(
        SalesRecord.branch_id, SalesRecord.business_date, SalesRecord.transaction_id).subquery()
    transaction_counts = dict(db.execute(select(transaction_groups.c.branch_id,
        func.count()).group_by(transaction_groups.c.branch_id)).all())
    granularity_rows = db.execute(select(SalesRecord.branch_id,
        func.sum(case((SalesRecord.granularity == "TRANSACTION", 1), else_=0)),
        func.sum(case((SalesRecord.granularity == "AGGREGATED", 1), else_=0)))
        .join(DailyUpload, DailyUpload.id == SalesRecord.source_upload_id)
        .where(*filters).group_by(SalesRecord.branch_id)).all()
    granularity_by_branch = {bid: (transaction_rows or 0, aggregated_rows or 0)
        for bid, transaction_rows, aggregated_rows in granularity_rows}
    previous_filters = _sales_filters(membership.company_id,
        period.previous_start, period.previous_end, branch_id, scope)
    previous_rows = db.execute(select(Branch.id, func.sum(SalesRecord.net_amount))
        .join(SalesRecord, SalesRecord.branch_id == Branch.id)
        .join(DailyUpload, DailyUpload.id == SalesRecord.source_upload_id)
        .where(Branch.company_id == membership.company_id, *previous_filters)
        .group_by(Branch.id)).all()
    previous_revenue = dict(previous_rows)
    result = []
    for bid, name, revenue, lines in rows:
        transaction_rows, aggregated_rows = granularity_by_branch.get(bid, (0, 0))
        transaction_coverage = (
            "UNAVAILABLE" if not transaction_rows else
            "PARTIAL" if aggregated_rows else "COMPLETE")
        known_transactions = transaction_counts.get(bid) if transaction_rows else None
        previous = previous_revenue.get(bid)
        change = None if previous in (None, ZERO) else (
            (revenue - previous) / abs(previous) * Decimal("100")).quantize(Decimal("0.01"))
        result.append({"branch_id": bid, "branch_name": name, "revenue": revenue,
            "previous_revenue": previous, "change_percent": change,
            "sales_lines": lines, "transaction_count": known_transactions,
            "transaction_count_coverage_status": transaction_coverage})
    return {"currency": company.currency, "period": period.as_dict(), "branches": result,
        "highest_revenue_branch_id": result[0]["branch_id"] if result else None,
        "lowest_revenue_branch_id": result[-1]["branch_id"] if result else None}


def product_performance(db: Session, membership: CompanyMembership,
                        period: AnalyticsPeriod, branch_id: UUID | None,
                        scope: BranchAccessScope) -> dict:
    company = db.get(Company, membership.company_id)
    filters = _sales_filters(membership.company_id, period.start, period.end, branch_id, scope)
    rows = db.execute(select(Product.id, Product.sku, Product.product_name,
        Product.unit_of_measure, ProductCategory.name, func.sum(SalesRecord.quantity),
        func.sum(SalesRecord.net_amount), func.count(SalesRecord.id))
        .join(SalesRecord, SalesRecord.product_id == Product.id)
        .join(DailyUpload, DailyUpload.id == SalesRecord.source_upload_id)
        .outerjoin(ProductCategory, ProductCategory.id == Product.category_id)
        .where(Product.company_id == membership.company_id, *filters)
        .group_by(Product.id, Product.sku, Product.product_name, Product.unit_of_measure, ProductCategory.name)
        .order_by(func.sum(SalesRecord.net_amount).desc())).all()
    products = [{"product_id": pid, "sku": sku, "product_name": name,
        "category": category, "unit": unit, "quantity": quantity, "revenue": revenue,
        "sales_lines": lines} for pid, sku, name, unit, category, quantity, revenue, lines in rows]
    category_rows = db.execute(select(ProductCategory.id, ProductCategory.name,
        func.sum(SalesRecord.net_amount)).join(Product, Product.category_id == ProductCategory.id)
        .join(SalesRecord, SalesRecord.product_id == Product.id)
        .join(DailyUpload, DailyUpload.id == SalesRecord.source_upload_id)
        .where(ProductCategory.company_id == membership.company_id, *filters)
        .group_by(ProductCategory.id, ProductCategory.name)
        .order_by(func.sum(SalesRecord.net_amount).desc())).all()
    trend_rows = db.execute(select(Product.id, Product.sku, Product.product_name,
        Product.unit_of_measure, SalesRecord.business_date,
        func.sum(SalesRecord.quantity), func.sum(SalesRecord.net_amount))
        .join(SalesRecord, SalesRecord.product_id == Product.id)
        .join(DailyUpload, DailyUpload.id == SalesRecord.source_upload_id)
        .where(Product.company_id == membership.company_id, *filters)
        .group_by(Product.id, Product.sku, Product.product_name,
            Product.unit_of_measure, SalesRecord.business_date)
        .order_by(SalesRecord.business_date, Product.product_name)).all()
    return {"currency": company.currency, "period": period.as_dict(),
        "top_products": products[:10], "lowest_revenue_products": list(reversed(products[-10:])),
        "product_trends": [{"product_id": pid, "sku": sku, "product_name": name,
            "unit": unit, "business_date": business_date, "quantity": quantity,
            "revenue": revenue} for pid, sku, name, unit, business_date, quantity, revenue in trend_rows],
        "categories": [{"category_id": cid, "category": name, "revenue": revenue}
            for cid, name, revenue in category_rows]}


def _latest_inventory_query(company_id: UUID, as_of: date, branch_id: UUID | None,
                            scope: BranchAccessScope):
    conditions = [InventorySnapshot.company_id == company_id,
        InventorySnapshot.business_date <= as_of,
        DailyUpload.company_id == company_id,
        DailyUpload.branch_id == InventorySnapshot.branch_id,
        DailyUpload.business_date == InventorySnapshot.business_date,
        DailyUpload.is_current.is_(True), DailyUpload.processing_status == "COMPLETED"]
    conditions.extend(scope.criteria(InventorySnapshot.company_id,
        InventorySnapshot.branch_id))
    latest = select(InventorySnapshot.branch_id.label("branch_id"),
        InventorySnapshot.product_id.label("product_id"),
        InventorySnapshot.batch_number.label("batch_number"),
        func.max(InventorySnapshot.business_date).label("business_date")).join(
        DailyUpload, DailyUpload.id == InventorySnapshot.source_upload_id
    ).where(*conditions).group_by(InventorySnapshot.branch_id,
        InventorySnapshot.product_id, InventorySnapshot.batch_number).subquery()
    return select(InventorySnapshot).join(latest, and_(
        InventorySnapshot.branch_id == latest.c.branch_id,
        InventorySnapshot.product_id == latest.c.product_id,
        InventorySnapshot.batch_number == latest.c.batch_number,
        InventorySnapshot.business_date == latest.c.business_date,
    )).join(DailyUpload, DailyUpload.id == InventorySnapshot.source_upload_id).where(
        InventorySnapshot.company_id == company_id,
        DailyUpload.company_id == company_id,
        DailyUpload.branch_id == InventorySnapshot.branch_id,
        DailyUpload.business_date == InventorySnapshot.business_date,
        DailyUpload.is_current.is_(True), DailyUpload.processing_status == "COMPLETED",
        *scope.criteria(InventorySnapshot.company_id, InventorySnapshot.branch_id))


def _inventory_coverage_status(product: Product, snapshots: list[InventorySnapshot],
        declarations: list[StockCoverageDeclaration]) -> tuple[str, list[str], Decimal | None]:
    """Apply the existing ingredient, batch, and closing-stock coverage rules."""
    reasons: set[str] = set()
    if not declarations:
        return "UNREPORTED", ["MISSING_INVENTORY_COVERAGE"], None
    if any(row.unit.casefold() != product.unit_of_measure.casefold()
            for row in declarations) or any(row.unit.casefold() != product.unit_of_measure.casefold()
            for row in snapshots):
        return "UNIT_MISMATCH", ["UNIT_MISMATCH"], None

    for row in snapshots:
        if row.closing_quantity < 0:
            reasons.add("INVALID_STOCK_QUANTITY")
    ingredient = [row for row in declarations
        if row.coverage_dimension == "INGREDIENT" and row.scope_type == "INGREDIENT"]
    batch = [row for row in declarations
        if row.coverage_dimension == "BATCH" and row.scope_type == "ALL_BATCHES"]
    if len(ingredient) != 1 or len(batch) != 1:
        return "INVALID_DATA" if len(ingredient) > 1 or len(batch) > 1 else "UNREPORTED", [
            "CONFLICTING_INVENTORY_COVERAGE" if len(ingredient) > 1 or len(batch) > 1
            else "MISSING_INGREDIENT_OR_BATCH_COVERAGE"], None

    required = [ingredient[0], batch[0]]
    broad = [row for row in declarations if row.coverage_dimension == "CLOSING_STOCK"
        and row.scope_type in {"INGREDIENT", "ALL_BATCHES"}]
    batch_closing = [row for row in declarations if row.coverage_dimension == "CLOSING_STOCK"
        and row.scope_type == "BATCH"]
    batches = {row.batch_number or "" for row in snapshots}
    batches.update(row.batch_number or "" for row in batch_closing)
    if broad and batch_closing or len(broad) > 1:
        return "INVALID_DATA", ["CONFLICTING_CLOSING_STOCK_COVERAGE"], None
    if broad:
        required.append(broad[0])
        if broad[0].status == "COMPLETE" and not snapshots:
            reasons.add("COMPLETE_CLOSING_COVERAGE_WITHOUT_SNAPSHOT")
        if broad[0].status == "NO_STOCK" and any(row.closing_quantity > 0 for row in snapshots):
            reasons.add("CONTRADICTORY_NO_STOCK_CLOSING")
    elif batch_closing:
        closing_by_batch = {row.batch_number or "": row for row in batch_closing}
        if not batches or not batches.issubset(closing_by_batch):
            reasons.add("INCOMPLETE_CLOSING_BATCH_COVERAGE")
        else:
            required.extend(closing_by_batch[key] for key in sorted(batches))
            for batch_number in batches:
                batch_rows = [row for row in snapshots
                    if (row.batch_number or "") == batch_number]
                declaration = closing_by_batch[batch_number]
                if declaration.status == "COMPLETE" and len(batch_rows) != 1:
                    reasons.add("INVALID_COMPLETE_CLOSING_BATCH")
                if declaration.status == "NO_STOCK" and any(
                        row.closing_quantity > 0 for row in batch_rows):
                    reasons.add("CONTRADICTORY_NO_STOCK_CLOSING")
    else:
        reasons.add("MISSING_CLOSING_STOCK_COVERAGE")

    if reasons:
        return "INVALID_DATA", sorted(reasons), None
    states = {row.status for row in required}
    if "UNIT_MISMATCH" in states:
        return "UNIT_MISMATCH", ["UNIT_MISMATCH"], None
    if "PARTIAL" in states:
        return "PARTIAL", ["PARTIAL_INVENTORY_COVERAGE"], None
    if "UNREPORTED" in states:
        return "UNREPORTED", ["UNREPORTED_INVENTORY_COVERAGE"], None
    if "NOT_APPLICABLE" in states:
        return "NOT_APPLICABLE", ["INVENTORY_NOT_APPLICABLE"], None
    if not states.issubset({"COMPLETE", "NO_STOCK"}):
        return "INVALID_DATA", ["INVALID_INVENTORY_COVERAGE_STATUS"], None
    if "NO_STOCK" in states:
        return "NO_STOCK", [], ZERO
    if not snapshots:
        return "INVALID_DATA", ["COMPLETE_CLOSING_COVERAGE_WITHOUT_SNAPSHOT"], None
    return "COMPLETE", [], sum((row.closing_quantity for row in snapshots), ZERO)


def inventory_overview(db: Session, membership: CompanyMembership, as_of: date,
                       branch_id: UUID | None, scope: BranchAccessScope) -> dict:
    rows = db.execute(_latest_inventory_query(membership.company_id, as_of, branch_id, scope)
        .with_only_columns(InventorySnapshot.id, InventorySnapshot.branch_id,
            InventorySnapshot.product_id, InventorySnapshot.batch_number,
            InventorySnapshot.closing_quantity, InventorySnapshot.unit,
            InventorySnapshot.expiry_date, InventorySnapshot.unit_cost,
            InventorySnapshot.business_date)
        .join(Product, Product.id == InventorySnapshot.product_id)
        .add_columns(Product.sku, Product.product_name, Branch.name.label("branch_name"))
        .join(Branch, Branch.id == InventorySnapshot.branch_id)
    ).all()
    scoped_branches = db.scalars(select(Branch).where(
        *scope.criteria(Branch.company_id, Branch.id)).order_by(Branch.name)).all()
    branch_ids = [branch.id for branch in scoped_branches]
    latest_uploads = db.scalars(select(DailyUpload).where(
        DailyUpload.company_id == membership.company_id,
        DailyUpload.branch_id.in_(branch_ids) if branch_ids else False,
        DailyUpload.business_date <= as_of,
        DailyUpload.is_current.is_(True),
        DailyUpload.processing_status == "COMPLETED",
    ).order_by(DailyUpload.business_date.desc(), DailyUpload.version.desc())).all()
    latest_by_branch: dict[UUID, DailyUpload] = {}
    for upload in latest_uploads:
        latest_by_branch.setdefault(upload.branch_id, upload)
    latest_upload_ids = [upload.id for upload in latest_by_branch.values()]
    observed_product_ids = set(db.scalars(select(InventorySnapshot.product_id).where(
        InventorySnapshot.company_id == membership.company_id,
        InventorySnapshot.source_upload_id.in_(latest_upload_ids) if latest_upload_ids else False,
    )).all())
    product_query = select(Product).where(Product.company_id == membership.company_id,
        Product.is_active.is_(True))
    if observed_product_ids:
        product_query = product_query.where(or_(Product.product_kind == "INGREDIENT",
            Product.id.in_(observed_product_ids)))
    else:
        product_query = product_query.where(Product.product_kind == "INGREDIENT")
    coverage_products = db.scalars(product_query.order_by(Product.sku)).all()
    coverage_product_ids = [product.id for product in coverage_products]
    latest_snapshots: dict[tuple[UUID, UUID], list[InventorySnapshot]] = {}
    if latest_upload_ids and coverage_product_ids:
        snapshot_facts = db.scalars(select(InventorySnapshot).where(
            InventorySnapshot.company_id == membership.company_id,
            InventorySnapshot.source_upload_id.in_(latest_upload_ids),
            InventorySnapshot.product_id.in_(coverage_product_ids),
        )).all()
        for snapshot in snapshot_facts:
            latest_snapshots.setdefault((snapshot.source_upload_id, snapshot.product_id), []).append(snapshot)
    declarations_by_key: dict[tuple[UUID, UUID], list[StockCoverageDeclaration]] = {}
    if latest_upload_ids and coverage_product_ids:
        declarations = db.scalars(select(StockCoverageDeclaration).where(
            StockCoverageDeclaration.company_id == membership.company_id,
            StockCoverageDeclaration.source_upload_id.in_(latest_upload_ids),
            StockCoverageDeclaration.ingredient_product_id.in_(coverage_product_ids),
        )).all()
        for declaration in declarations:
            declarations_by_key.setdefault((declaration.source_upload_id,
                declaration.ingredient_product_id), []).append(declaration)
    ingredient_coverage = []
    for branch in scoped_branches:
        latest_upload = latest_by_branch.get(branch.id)
        for product in coverage_products:
            if latest_upload is None:
                status, reasons, quantity = "UNAVAILABLE", ["NO_COMPLETED_CURRENT_UPLOAD"], None
                snapshot_date = None
            else:
                product_snapshots = latest_snapshots.get((latest_upload.id, product.id), [])
                status, reasons, quantity = _inventory_coverage_status(product,
                    product_snapshots,
                    declarations_by_key.get((latest_upload.id, product.id), []))
                snapshot_date = latest_upload.business_date
            ingredient_coverage.append({"branch_id": branch.id,
                "branch_name": branch.name, "ingredient_id": product.id,
                "sku": product.sku, "product_name": product.product_name,
                "unit": product.unit_of_measure, "snapshot_date": snapshot_date,
                "quantity": quantity, "status": status, "reason_codes": reasons})
    if not ingredient_coverage or all(row["status"] == "UNAVAILABLE" for row in ingredient_coverage):
        coverage_status = "UNAVAILABLE"
    elif all(row["status"] in {"COMPLETE", "NO_STOCK"} for row in ingredient_coverage):
        coverage_status = "COMPLETE"
    elif any(row["status"] == "UNIT_MISMATCH" for row in ingredient_coverage):
        coverage_status = "UNIT_MISMATCH"
    elif any(row["status"] == "INVALID_DATA" for row in ingredient_coverage):
        coverage_status = "INVALID_DATA"
    else:
        coverage_status = "INCOMPLETE"
    products = [{"branch_id": bid, "branch_name": branch_name, "product_id": pid,
        "sku": sku, "product_name": name, "batch_number": batch,
        "quantity": quantity, "unit": unit, "snapshot_date": snapshot_date}
        for _, bid, pid, batch, quantity, unit, expiry, unit_cost, snapshot_date,
            sku, name, branch_name in rows]
    expiring = [{"branch_id": bid, "branch_name": branch_name, "product_id": pid,
        "sku": sku, "product_name": name, "batch_number": batch,
        "expiry_date": expiry, "quantity": quantity, "unit": unit}
        for _, bid, pid, batch, quantity, unit, expiry, _, _, sku, name, branch_name in rows
        if expiry is not None and as_of <= expiry <= as_of + timedelta(days=30)]
    expired = [{"branch_id": bid, "branch_name": branch_name, "product_id": pid,
        "sku": sku, "product_name": name, "batch_number": batch,
        "expiry_date": expiry, "quantity": quantity, "unit": unit}
        for _, bid, pid, batch, quantity, unit, expiry, _, _, sku, name, branch_name in rows
        if expiry is not None and expiry < as_of]
    discrepancy_filters = [DailyUpload.company_id == membership.company_id,
        DailyUpload.is_current.is_(True), DailyUpload.processing_status == "COMPLETED",
        DailyUpload.business_date >= as_of - timedelta(days=30),
        DailyUpload.business_date <= as_of,
        UploadValidationIssue.code == "INVENTORY_RECONCILIATION"]
    discrepancy_filters.extend(scope.criteria(DailyUpload.company_id,
        DailyUpload.branch_id))
    discrepancies = db.execute(select(UploadValidationIssue.upload_id,
        UploadValidationIssue.message, DailyUpload.branch_id, Branch.name,
        DailyUpload.business_date).join(DailyUpload,
        DailyUpload.id == UploadValidationIssue.upload_id).join(
        Branch, Branch.id == DailyUpload.branch_id).where(*discrepancy_filters)
        .order_by(DailyUpload.business_date.desc())).all()
    return {"as_of_date": as_of, "branch_id": branch_id, "products": products,
        "coverage_status": coverage_status, "ingredient_coverage": ingredient_coverage,
        "expiring_batches": expiring, "expired_batches": expired,
        "reconciliation_discrepancies": [{"upload_id": uid, "branch_id": bid,
            "branch_name": branch_name, "business_date": business_date, "message": message}
            for uid, message, bid, branch_name, business_date in discrepancies],
        "low_stock_thresholds_configured": False}


def waste_overview(db: Session, membership: CompanyMembership,
                   period: AnalyticsPeriod, branch_id: UUID | None,
                   scope: BranchAccessScope) -> dict:
    company = db.get(Company, membership.company_id)
    snapshot_query = _inventory_period_query(
        membership.company_id, period.start, period.end, branch_id, scope)
    snapshot_rows = db.execute(select(
        InventorySnapshot, Branch.name, Product.sku, Product.product_name,
    ).select_from(InventorySnapshot)
        .join(DailyUpload, DailyUpload.id == InventorySnapshot.source_upload_id)
        .join(Product, Product.id == InventorySnapshot.product_id)
        .join(Branch, Branch.id == InventorySnapshot.branch_id)
        .where(*snapshot_query.whereclause.clauses)
        .order_by(InventorySnapshot.business_date, Branch.name, Product.sku,
            InventorySnapshot.batch_number)).all()
    movement_rows = db.execute(select(
        StockMovement, Branch.name, Product.sku, Product.product_name,
    ).select_from(StockMovement)
        .join(Branch, Branch.id == StockMovement.branch_id)
        .join(Product, Product.id == StockMovement.ingredient_product_id)
        .outerjoin(DailyUpload, DailyUpload.id == StockMovement.source_upload_id)
        .where(
            StockMovement.company_id == membership.company_id,
            StockMovement.movement_date >= period.start,
            StockMovement.movement_date <= period.end,
            StockMovement.movement_type.in_(("WASTE", "DAMAGE")),
            StockMovement.voided_at.is_(None),
            Branch.company_id == membership.company_id,
            Product.company_id == membership.company_id,
            *scope.criteria(StockMovement.company_id, StockMovement.branch_id),
            or_(
                and_(StockMovement.origin_type == "MANUAL",
                    StockMovement.source_upload_id.is_(None)),
                and_(StockMovement.origin_type == "UPLOAD",
                    DailyUpload.id == StockMovement.source_upload_id,
                    DailyUpload.company_id == membership.company_id,
                    DailyUpload.branch_id == StockMovement.branch_id,
                    DailyUpload.is_current.is_(True),
                    DailyUpload.processing_status == "COMPLETED"),
            ),
        ).order_by(StockMovement.movement_date, Branch.name, Product.sku,
            StockMovement.movement_type, StockMovement.id)).all()
    coverage_rows = db.execute(select(
        StockCoverageDeclaration, Branch.name, Product.sku, Product.product_name,
    ).join(DailyUpload, DailyUpload.id == StockCoverageDeclaration.source_upload_id)
        .join(Branch, Branch.id == StockCoverageDeclaration.branch_id)
        .join(Product, Product.id == StockCoverageDeclaration.ingredient_product_id)
        .where(
            StockCoverageDeclaration.company_id == membership.company_id,
            StockCoverageDeclaration.business_date >= period.start,
            StockCoverageDeclaration.business_date <= period.end,
            StockCoverageDeclaration.coverage_dimension == "MOVEMENT_CATEGORY",
            StockCoverageDeclaration.movement_type.in_(("WASTE", "DAMAGE")),
            DailyUpload.company_id == membership.company_id,
            DailyUpload.branch_id == StockCoverageDeclaration.branch_id,
            DailyUpload.business_date == StockCoverageDeclaration.business_date,
            DailyUpload.is_current.is_(True),
            DailyUpload.processing_status == "COMPLETED",
            Branch.company_id == membership.company_id,
            Product.company_id == membership.company_id,
            *scope.criteria(StockCoverageDeclaration.company_id,
                StockCoverageDeclaration.branch_id),
        ).order_by(StockCoverageDeclaration.business_date, Branch.name,
            Product.sku, StockCoverageDeclaration.movement_type)).all()
    current_upload_scopes = db.execute(select(DailyUpload, Branch.name)
        .join(Branch, Branch.id == DailyUpload.branch_id)
        .where(DailyUpload.company_id == membership.company_id,
            DailyUpload.business_date >= period.start,
            DailyUpload.business_date <= period.end,
            DailyUpload.is_current.is_(True),
            DailyUpload.processing_status == "COMPLETED",
            Branch.company_id == membership.company_id,
            *scope.criteria(DailyUpload.company_id, DailyUpload.branch_id))).all()
    tracked_ingredients = db.scalars(select(Product).where(
        Product.company_id == membership.company_id,
        Product.product_kind == "INGREDIENT", Product.is_active.is_(True),
    )).all()

    # Snapshot quantities are aggregate observations without event identifiers.
    # Never add them to ledger totals for the same ingredient/date/category.
    scopes: dict[tuple, dict] = {}

    def get_scope(bid, branch_name, pid, sku, name, unit, business_date):
        key = (bid, pid, business_date, unit)
        return scopes.setdefault(key, {
            "branch_id": bid, "branch_name": branch_name, "product_id": pid,
            "sku": sku, "product_name": name, "unit": unit,
            "business_date": business_date, "snapshots": [],
            "movements": {"WASTE": [], "DAMAGE": []},
            "complete_categories": set(),
        })

    for snapshot, branch_name, sku, name in snapshot_rows:
        get_scope(snapshot.branch_id, branch_name, snapshot.product_id, sku, name,
            snapshot.unit, snapshot.business_date)["snapshots"].append(snapshot)
    for movement, branch_name, sku, name in movement_rows:
        get_scope(movement.branch_id, branch_name, movement.ingredient_product_id,
            sku, name, movement.unit, movement.movement_date)["movements"][
                movement.movement_type].append(movement)
    for declaration, branch_name, sku, name in coverage_rows:
        scope_entry = get_scope(declaration.branch_id, branch_name,
            declaration.ingredient_product_id, sku, name, declaration.unit,
            declaration.business_date)
        if (declaration.status == "COMPLETE"
                and declaration.scope_type in {"INGREDIENT", "ALL_BATCHES"}):
            scope_entry["complete_categories"].add(declaration.movement_type)
    # Active ingredients are expected coverage subjects for each current
    # completed daily upload. Missing rows/declarations therefore remain
    # unknown instead of disappearing from the company or branch totals.
    for upload, branch_name in current_upload_scopes:
        for product in tracked_ingredients:
            get_scope(upload.branch_id, branch_name, product.id, product.sku,
                product.product_name, product.unit_of_measure, upload.business_date)

    def category_value(scope: dict, kind: str) -> dict:
        field = "wasted_quantity" if kind == "WASTE" else "damaged_quantity"
        snapshot_amount = sum((getattr(row, field) for row in scope["snapshots"]), ZERO)
        positive_snapshots = [row for row in scope["snapshots"]
            if getattr(row, field) > 0]
        snapshot_cost_complete = all(row.unit_cost is not None
            for row in positive_snapshots)
        snapshot_value = sum((getattr(row, field) * row.unit_cost
            for row in positive_snapshots if row.unit_cost is not None), ZERO)
        movements = scope["movements"][kind]
        ledger_amount = sum((row.quantity for row in movements), ZERO)
        declared_complete = kind in scope["complete_categories"]
        overlap = bool(positive_snapshots and movements)

        if declared_complete:
            # Complete category coverage makes the ledger authoritative; its
            # event quantities are counted once even if the snapshot also reports them.
            if snapshot_amount > 0 and snapshot_amount != ledger_amount:
                # A complete ledger and positive snapshot disagree, and the
                # snapshot has no event references to reconcile the difference.
                return {"amount": None, "status": "PARTIAL", "value": None,
                    "cost_complete": False, "overlap": "AMBIGUOUS"}
            return {"amount": ledger_amount, "status": "COMPLETE",
                "value": ZERO if ledger_amount == 0 else None,
                "cost_complete": True if ledger_amount == 0 else False,
                "overlap": "LEDGER_AUTHORITATIVE" if overlap else "NONE"}
        if movements:
            # Observed ledger events remain visible, but the total is partial
            # because unreported events and snapshot overlap cannot be resolved.
            return {"amount": ledger_amount, "status": "PARTIAL",
                "value": None, "cost_complete": False,
                "overlap": "AMBIGUOUS" if overlap else "NONE"}
        if snapshot_amount > 0:
            return {"amount": snapshot_amount, "status": "PARTIAL",
                "value": snapshot_value,
                "cost_complete": snapshot_cost_complete, "overlap": "NONE"}
        # Snapshot fields are non-nullable and blank cells were ingested as zero;
        # without explicit category coverage, zero is unknown rather than confirmed.
        return {"amount": None, "status": "UNAVAILABLE", "value": None,
            "cost_complete": False, "overlap": "NONE"}

    for scope_entry in scopes.values():
        scope_entry["categories"] = {kind: category_value(scope_entry, kind)
            for kind in ("DAMAGE", "WASTE")}

    def summarize(entries: list[dict]) -> dict:
        result = {}
        for kind, name in (("DAMAGE", "damaged"), ("WASTE", "wasted")):
            states = [entry["categories"][kind] for entry in entries]
            amounts = [state["amount"] for state in states]
            result[name] = (None if not states or any(value is None for value in amounts)
                else sum(amounts, ZERO))
            if states and all(state["status"] == "COMPLETE" for state in states):
                status = "COMPLETE"
            elif any(state["amount"] is not None for state in states):
                status = "PARTIAL"
            else:
                status = "UNAVAILABLE"
            result[f"{name}_coverage_status"] = status
        return result

    scope_list = list(scopes.values())
    product_groups: dict[tuple, list[dict]] = {}
    branch_groups: dict[UUID, list[dict]] = {}
    unit_groups: dict[tuple, list[dict]] = {}
    trend_groups: dict[tuple, list[dict]] = {}
    for scope_entry in scope_list:
        product_groups.setdefault((scope_entry["product_id"], scope_entry["unit"]), []).append(scope_entry)
        branch_groups.setdefault(scope_entry["branch_id"], []).append(scope_entry)
        unit_groups.setdefault((scope_entry["sku"], scope_entry["unit"]), []).append(scope_entry)
        trend_groups.setdefault((scope_entry["business_date"], scope_entry["unit"]), []).append(scope_entry)

    by_product = []
    for (pid, unit), entries in product_groups.items():
        first = entries[0]
        by_product.append({"product_id": pid, "sku": first["sku"],
            "product_name": first["product_name"], "unit": unit,
            **summarize(entries)})
    by_branch = [{"branch_id": bid, "branch_name": entries[0]["branch_name"],
        **summarize(entries)} for bid, entries in branch_groups.items()]
    by_unit = [{"sku": sku, "unit": unit, **summarize(entries)}
        for (sku, unit), entries in unit_groups.items()]
    trend = [{"business_date": business_date, "unit": unit, **summarize(entries)}
        for (business_date, unit), entries in sorted(trend_groups.items())]

    all_states = [state for scope_entry in scope_list
        for state in scope_entry["categories"].values()]
    if not scope_list:
        quantity_status = "UNAVAILABLE"
    elif all(state["status"] == "COMPLETE" for state in all_states):
        quantity_status = "COMPLETE"
    else:
        quantity_status = "PARTIAL"
    overlap_states = {state["overlap"] for state in all_states}
    if "AMBIGUOUS" in overlap_states:
        reconciliation_status = "AMBIGUOUS"
    elif "LEDGER_AUTHORITATIVE" in overlap_states:
        reconciliation_status = "LEDGER_AUTHORITATIVE"
    else:
        reconciliation_status = "NO_OVERLAP"
    positive_states = [state for state in all_states
        if state["amount"] is not None and state["amount"] > 0]
    all_amounts_known = bool(all_states) and all(
        state["amount"] is not None for state in all_states)
    cost_complete = all_amounts_known and all(
        state["cost_complete"] for state in positive_states)
    has_waste = bool(positive_states)
    valued = sum((state["value"] for state in positive_states
        if state["value"] is not None), ZERO)
    recorded_value = (valued if has_waste and cost_complete else
        ZERO if quantity_status == "COMPLETE" and not has_waste else None)

    discrepancies = db.execute(select(UploadValidationIssue.upload_id,
        UploadValidationIssue.message, DailyUpload.branch_id, Branch.name,
        DailyUpload.business_date).join(DailyUpload, DailyUpload.id == UploadValidationIssue.upload_id)
        .join(Branch, Branch.id == DailyUpload.branch_id)
        .where(DailyUpload.company_id == membership.company_id,
            DailyUpload.is_current.is_(True), DailyUpload.processing_status == "COMPLETED",
            DailyUpload.business_date >= period.start, DailyUpload.business_date <= period.end,
            UploadValidationIssue.code == "INVENTORY_RECONCILIATION",
            *scope.criteria(DailyUpload.company_id, DailyUpload.branch_id))
        .order_by(DailyUpload.business_date.desc())).all()
    return {"currency": company.currency, "period": period.as_dict(),
        "damaged_by_product": by_product, "wasted_by_product": by_product,
        "by_branch": by_branch, "by_unit": by_unit,
        "recorded_value": recorded_value, "cost_coverage_complete": cost_complete,
        "quantity_coverage_status": quantity_status,
        "snapshot_ledger_reconciliation": reconciliation_status,
        "trend": trend,
        "reconciliation_discrepancies": [{"upload_id": upload_id, "branch_id": bid,
            "branch_name": branch_name, "business_date": business_date, "message": message}
            for upload_id, message, bid, branch_name, business_date in discrepancies]}

def purchases_overview(db: Session, membership: CompanyMembership,
                       period: AnalyticsPeriod, branch_id: UUID | None,
                       scope: BranchAccessScope) -> dict:
    company = db.get(Company, membership.company_id)
    filters = [PurchaseLine.company_id == membership.company_id,
        DailyUpload.company_id == membership.company_id,
        DailyUpload.branch_id == PurchaseLine.branch_id,
        DailyUpload.business_date == PurchaseLine.business_date,
        DailyUpload.is_current.is_(True),
        DailyUpload.processing_status == "COMPLETED"]
    filters.extend(scope.criteria(PurchaseLine.company_id, PurchaseLine.branch_id))
    missing_receipt_dates = db.scalar(select(func.count(PurchaseLine.id))
        .join(DailyUpload, DailyUpload.id == PurchaseLine.source_upload_id)
        .where(*filters, PurchaseLine.receipt_date.is_(None))) or 0
    receipt_filters = [*filters, PurchaseLine.receipt_date >= period.start,
        PurchaseLine.receipt_date <= period.end]
    totals = db.execute(select(func.count(PurchaseLine.id),
        func.count(PurchaseLine.unit_purchase_price),
        func.sum(PurchaseLine.quantity_received * PurchaseLine.unit_purchase_price))
        .join(DailyUpload, DailyUpload.id == PurchaseLine.source_upload_id).where(*receipt_filters)).one()
    total_lines, priced_lines, known_spend = totals
    spend, receipt_date_status = _purchase_spend_result(
        total_lines, priced_lines, known_spend, missing_receipt_dates)
    suppliers = db.execute(select(PurchaseLine.supplier_name,
        func.count(PurchaseLine.id), func.count(PurchaseLine.unit_purchase_price),
        func.sum(PurchaseLine.quantity_received * PurchaseLine.unit_purchase_price))
        .join(DailyUpload, DailyUpload.id == PurchaseLine.source_upload_id).where(*receipt_filters)
        .group_by(PurchaseLine.supplier_name).order_by(func.sum(PurchaseLine.quantity_received * PurchaseLine.unit_purchase_price).desc())).all()
    products = db.execute(select(Product.id, Product.sku, Product.product_name,
        Product.unit_of_measure, func.sum(PurchaseLine.quantity_received),
        func.count(PurchaseLine.id), func.count(PurchaseLine.unit_purchase_price),
        func.sum(PurchaseLine.quantity_received * PurchaseLine.unit_purchase_price)).join(PurchaseLine, PurchaseLine.product_id == Product.id)
        .join(DailyUpload, DailyUpload.id == PurchaseLine.source_upload_id)
        .where(Product.company_id == membership.company_id, *receipt_filters)
        .group_by(Product.id, Product.sku, Product.product_name, Product.unit_of_measure)
        .order_by(func.sum(PurchaseLine.quantity_received).desc())).all()
    trend = db.execute(select(PurchaseLine.receipt_date, func.count(PurchaseLine.id),
        func.count(PurchaseLine.unit_purchase_price),
        func.sum(PurchaseLine.quantity_received * PurchaseLine.unit_purchase_price))
        .join(DailyUpload, DailyUpload.id == PurchaseLine.source_upload_id).where(*receipt_filters)
        .group_by(PurchaseLine.receipt_date).order_by(PurchaseLine.receipt_date)).all()
    return {"currency": company.currency, "period": period.as_dict(), "spend": spend,
        "receipt_date_coverage_status": receipt_date_status,
        "missing_receipt_date_lines": missing_receipt_dates,
        "priced_lines": priced_lines or 0, "total_lines": total_lines or 0,
        "supplier_purchases": [{"supplier": supplier or "Unspecified",
            "lines": count, "spend": value if count == priced else None}
            for supplier, count, priced, value in suppliers],
        "products": [{"product_id": pid, "sku": sku, "product_name": name,
            "unit": unit, "quantity": quantity, "spend": value if lines == priced else None, "lines": lines}
            for pid, sku, name, unit, quantity, lines, priced, value in products],
        "trend": [{"receipt_date": receipt_date,
            "spend": value if count == priced else None}
            for receipt_date, count, priced, value in trend]}


def alerts(db: Session, membership: CompanyMembership, period: AnalyticsPeriod,
           branch_id: UUID | None, scope: BranchAccessScope) -> dict:
    inventory = inventory_overview(db, membership, period.end, branch_id, scope)
    result = []
    for row in inventory["expired_batches"]:
        result.append({"id": f"expired:{row['branch_id']}:{row['product_id']}:{row['batch_number']}",
            "kind": "EXPIRED_STOCK", "severity": "CRITICAL",
            "title": "Expired stock on hand",
            "description": f"{row['quantity']} {row['unit']} of {row['product_name']} (batch {row['batch_number']}) expired {row['expiry_date']}.",
            "branch_id": row["branch_id"], "product_id": row["product_id"],
            "upload_id": None, "href": "/dashboard/analytics/inventory"})
    for row in inventory["expiring_batches"]:
        result.append({"id": f"expiry:{row['branch_id']}:{row['product_id']}:{row['batch_number']}",
            "kind": "EXPIRING_STOCK", "severity": "WARNING",
            "title": "Stock approaching expiry",
            "description": f"{row['quantity']} {row['unit']} of {row['product_name']} (batch {row['batch_number']}) expires {row['expiry_date']}.",
            "branch_id": row["branch_id"], "product_id": row["product_id"],
            "upload_id": None, "href": "/dashboard/analytics/inventory"})
    for discrepancy in inventory["reconciliation_discrepancies"]:
        upload_id = discrepancy["upload_id"]
        message = discrepancy["message"]
        result.append({"id": f"reconciliation:{upload_id}:{message[:24]}",
            "kind": "INVENTORY_DISCREPANCY", "severity": "WARNING",
            "title": "Inventory figures need review", "description": message,
            "branch_id": discrepancy["branch_id"], "product_id": None, "upload_id": upload_id,
            "href": "/dashboard/uploads"})

    branches = list(db.scalars(select(Branch).where(
        Branch.company_id == membership.company_id, Branch.is_active.is_(True),
        *scope.criteria(Branch.company_id, Branch.id))).all())
    latest_uploads = db.execute(select(DailyUpload.branch_id,
        func.max(DailyUpload.business_date)).where(
        DailyUpload.company_id == membership.company_id, DailyUpload.is_current.is_(True),
        DailyUpload.processing_status == "COMPLETED",
        *scope.criteria(DailyUpload.company_id, DailyUpload.branch_id)
        ).group_by(DailyUpload.branch_id)).all()
    latest = dict(latest_uploads)
    today = date.today()
    for branch in branches:
        last_day = latest.get(branch.id)
        if last_day is None:
            result.append({"id": f"upload-missing:{branch.id}", "kind": "MISSING_UPLOAD",
                "severity": "WARNING", "title": "No completed workbook found",
                "description": f"{branch.name} has no completed current workbook.",
                "branch_id": branch.id, "product_id": None, "upload_id": None,
                "href": "/dashboard/uploads"})
        elif (today - last_day).days > 3:
            result.append({"id": f"upload-stale:{branch.id}", "kind": "OUTDATED_UPLOAD",
                "severity": "WARNING", "title": "Branch data may be outdated",
                "description": f"The latest completed workbook for {branch.name} is dated {last_day}.",
                "branch_id": branch.id, "product_id": None, "upload_id": None,
                "href": "/dashboard/uploads"})
    return {"as_of_date": period.end, "alerts": result}
