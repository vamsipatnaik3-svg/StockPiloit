from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.branch_scope import BranchAccessScope, resolve_branch_scope
from app.api.dependencies import require_roles
from app.db.session import get_db
from app.models import CompanyMembership, Product
from app.schemas.theoretical_consumption import TheoreticalConsumptionResponse
from app.schemas.actual_consumption import ActualConsumptionResponse
from app.schemas.variance_intelligence import VarianceIntelligenceResponse
from app.schemas.analytics import (AlertsResponse, BranchPerformanceResponse,
    InventoryOverviewResponse, OverviewResponse, ProductPerformanceResponse,
    PurchasesOverviewResponse, SalesTrendsResponse, WasteOverviewResponse)
from app.services.analytics import (AnalyticsPeriod, alerts, branch_performance,
    inventory_overview, overview, product_performance, purchases_overview,
    resolve_period, sales_trends, waste_overview)
from app.services.theoretical_consumption import calculate_theoretical_consumption
from app.services.theoretical_consumption_queries import load_theoretical_inputs
from app.services.actual_consumption import actual_ingredient_consumption
from app.services.variance_intelligence import variance_intelligence

router = APIRouter(tags=["Analytics"])


def _filters(db: Session, membership: CompanyMembership,
             start_date: date | None, end_date: date | None,
             branch_id: UUID | None,
             branch_ids: list[UUID] | None = None
             ) -> tuple[AnalyticsPeriod, BranchAccessScope]:
    period = resolve_period(start_date, end_date)
    if branch_id is not None and branch_ids is not None:
        raise HTTPException(status_code=422,
            detail="Use either branch_id or branch_ids, not both.")
    requested = [branch_id] if branch_id is not None else branch_ids
    scope = resolve_branch_scope(db, membership,
        requested)
    return period, scope


ANALYTICS_ROLES = ("OWNER", "MANAGER", "ANALYST")


@router.get("/overview", response_model=OverviewResponse)
def get_overview(start_date: date | None = None, end_date: date | None = None,
        branch_id: UUID | None = None, branch_ids: list[UUID] | None = Query(default=None),
        membership: CompanyMembership = Depends(require_roles(*ANALYTICS_ROLES)),
        db: Session = Depends(get_db)):
    period, scope = _filters(db, membership, start_date, end_date, branch_id, branch_ids)
    return overview(db, membership, period, branch_id, scope)


@router.get("/sales/trends", response_model=SalesTrendsResponse)
def get_sales_trends(start_date: date | None = None, end_date: date | None = None,
        branch_id: UUID | None = None, branch_ids: list[UUID] | None = Query(default=None),
        membership: CompanyMembership = Depends(require_roles(*ANALYTICS_ROLES)),
        db: Session = Depends(get_db)):
    period, scope = _filters(db, membership, start_date, end_date, branch_id, branch_ids)
    return sales_trends(db, membership, period, branch_id, scope)


@router.get("/branches/performance", response_model=BranchPerformanceResponse)
def get_branch_performance(start_date: date | None = None, end_date: date | None = None,
        branch_id: UUID | None = None, branch_ids: list[UUID] | None = Query(default=None),
        membership: CompanyMembership = Depends(require_roles(*ANALYTICS_ROLES)),
        db: Session = Depends(get_db)):
    period, scope = _filters(db, membership, start_date, end_date, branch_id, branch_ids)
    return branch_performance(db, membership, period, branch_id, scope)


@router.get("/products/performance", response_model=ProductPerformanceResponse)
def get_product_performance(start_date: date | None = None, end_date: date | None = None,
        branch_id: UUID | None = None, branch_ids: list[UUID] | None = Query(default=None),
        membership: CompanyMembership = Depends(require_roles(*ANALYTICS_ROLES)),
        db: Session = Depends(get_db)):
    period, scope = _filters(db, membership, start_date, end_date, branch_id, branch_ids)
    return product_performance(db, membership, period, branch_id, scope)


@router.get("/inventory/overview", response_model=InventoryOverviewResponse)
def get_inventory_overview(as_of_date: date | None = None, branch_id: UUID | None = None,
        branch_ids: list[UUID] | None = Query(default=None),
        membership: CompanyMembership = Depends(require_roles(*ANALYTICS_ROLES)),
        db: Session = Depends(get_db)):
    _, scope = _filters(db, membership, None, None, branch_id, branch_ids)
    return inventory_overview(db, membership, as_of_date or date.today(), branch_id, scope)


@router.get("/inventory/expiry", response_model=InventoryOverviewResponse)
def get_inventory_expiry(as_of_date: date | None = None, branch_id: UUID | None = None,
        branch_ids: list[UUID] | None = Query(default=None),
        membership: CompanyMembership = Depends(require_roles(*ANALYTICS_ROLES)),
        db: Session = Depends(get_db)):
    _, scope = _filters(db, membership, None, None, branch_id, branch_ids)
    data = inventory_overview(db, membership, as_of_date or date.today(), branch_id, scope)
    return {**data, "products": []}


@router.get("/waste/overview", response_model=WasteOverviewResponse)
def get_waste_overview(start_date: date | None = None, end_date: date | None = None,
        branch_id: UUID | None = None, branch_ids: list[UUID] | None = Query(default=None),
        membership: CompanyMembership = Depends(require_roles(*ANALYTICS_ROLES)),
        db: Session = Depends(get_db)):
    period, scope = _filters(db, membership, start_date, end_date, branch_id, branch_ids)
    return waste_overview(db, membership, period, branch_id, scope)


@router.get("/purchases/overview", response_model=PurchasesOverviewResponse)
def get_purchases_overview(start_date: date | None = None, end_date: date | None = None,
        branch_id: UUID | None = None, branch_ids: list[UUID] | None = Query(default=None),
        membership: CompanyMembership = Depends(require_roles(*ANALYTICS_ROLES)),
        db: Session = Depends(get_db)):
    period, scope = _filters(db, membership, start_date, end_date, branch_id, branch_ids)
    return purchases_overview(db, membership, period, branch_id, scope)


@router.get("/alerts", response_model=AlertsResponse)
def get_alerts(start_date: date | None = None, end_date: date | None = None,
        branch_id: UUID | None = None, branch_ids: list[UUID] | None = Query(default=None),
        membership: CompanyMembership = Depends(require_roles(*ANALYTICS_ROLES)),
        db: Session = Depends(get_db)):
    period, scope = _filters(db, membership, start_date, end_date, branch_id, branch_ids)
    return alerts(db, membership, period, branch_id, scope)


@router.get("/ingredient-consumption/theoretical",
            response_model=TheoreticalConsumptionResponse)
def get_theoretical_ingredient_consumption(
        start_date: date | None = None, end_date: date | None = None,
        branch_id: UUID | None = None, branch_ids: list[UUID] | None = Query(default=None),
        ingredient_id: UUID | None = None,
        membership: CompanyMembership = Depends(require_roles(*ANALYTICS_ROLES)),
        db: Session = Depends(get_db)):
    period, scope = _filters(db, membership, start_date, end_date, branch_id, branch_ids)
    if ingredient_id is not None:
        ingredient = db.scalar(select(Product.id).where(
            Product.id == ingredient_id,
            Product.company_id == membership.company_id,
            Product.product_kind == "INGREDIENT",
        ))
        if ingredient is None:
            raise HTTPException(status_code=404, detail="Ingredient not found.")

    scopes, sales = load_theoretical_inputs(db, membership.company_id,
        period.start, period.end, scope)
    calculated = calculate_theoretical_consumption(scopes, sales,
        membership.company_id)
    items = calculated["items"]
    if ingredient_id is not None:
        items = [item for item in items if item["ingredient_id"] == ingredient_id]
    return {
        "start_date": period.start,
        "end_date": period.end,
        "branch_id": branch_id,
        "ingredient_id": ingredient_id,
        "items": items,
        "scopes": calculated["scopes"],
        "unresolved_sales": calculated["unresolved_sales"],
    }


@router.get("/ingredient-consumption/actual",
            response_model=ActualConsumptionResponse)
def get_actual_ingredient_consumption(
        start_date: date | None = None, end_date: date | None = None,
        branch_id: UUID | None = None, branch_ids: list[UUID] | None = Query(default=None),
        ingredient_id: UUID | None = None,
        membership: CompanyMembership = Depends(require_roles(*ANALYTICS_ROLES)),
        db: Session = Depends(get_db)):
    period, scope = _filters(db, membership, start_date, end_date, branch_id, branch_ids)
    if ingredient_id is not None:
        ingredient = db.scalar(select(Product.id).where(
            Product.id == ingredient_id,
            Product.company_id == membership.company_id,
            Product.product_kind == "INGREDIENT",
        ))
        if ingredient is None:
            raise HTTPException(status_code=404, detail="Ingredient not found.")
    calculated = actual_ingredient_consumption(db, membership.company_id,
        period.start, period.end, branch_id, ingredient_id, scope)
    return {
        "start_date": period.start,
        "end_date": period.end,
        "branch_id": branch_id,
        "ingredient_id": ingredient_id,
        **calculated,
    }


@router.get("/variance/intelligence", response_model=VarianceIntelligenceResponse)
def get_variance_intelligence(
        start_date: date | None = None, end_date: date | None = None,
        branch_id: UUID | None = None, branch_ids: list[UUID] | None = Query(default=None),
        ingredient_id: UUID | None = None,
        finding_type: str | None = None, severity: str | None = None,
        status: str | None = None,
        offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500),
        membership: CompanyMembership = Depends(require_roles(*ANALYTICS_ROLES)),
        db: Session = Depends(get_db)):
    period, scope = _filters(db, membership, start_date, end_date, branch_id, branch_ids)
    if ingredient_id is not None:
        ingredient = db.scalar(select(Product.id).where(
            Product.id == ingredient_id,
            Product.company_id == membership.company_id,
            Product.product_kind == "INGREDIENT",
        ))
        if ingredient is None:
            raise HTTPException(status_code=404, detail="Ingredient not found.")
    if severity is not None and severity not in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}:
        raise HTTPException(status_code=422, detail="Invalid severity.")
    if status is not None and status not in {
            "ANOMALY", "NORMAL", "INSUFFICIENT_BASELINE", "INCOMPLETE_DATA", "UNAVAILABLE"}:
        raise HTTPException(status_code=422, detail="Invalid finding status.")
    if finding_type is not None and finding_type not in {
            "CONSUMPTION_VARIANCE", "WASTE", "DAMAGE", "STAFF_CONSUMPTION",
            "WASTE_RATE", "DAMAGE_RATE", "POSITIVE_ADJUSTMENT", "NEGATIVE_ADJUSTMENT",
            "POSITIVE_ADJUSTMENT_FREQUENCY", "NEGATIVE_ADJUSTMENT_FREQUENCY",
            "DATA_QUALITY", "BRANCH_WASTE_RATE", "BRANCH_DAMAGE_RATE",
            "BRANCH_CONSUMPTION_VARIANCE"}:
        raise HTTPException(status_code=422, detail="Invalid finding type.")
    return variance_intelligence(db, membership.company_id, period.start, period.end,
        branch_id, ingredient_id, finding_type, severity, status, offset, limit, scope)
