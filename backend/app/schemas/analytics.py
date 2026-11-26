from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class Period(BaseModel):
    start_date: date
    end_date: date
    previous_start_date: date
    previous_end_date: date


class MetricComparison(BaseModel):
    current: Decimal | int | None
    previous: Decimal | int | None
    change_percent: Decimal | None


class Coverage(BaseModel):
    sales_lines: int
    sales_days: int
    latest_sales_date: date | None
    latest_upload_date: date | None


class SalesBranchCoverage(BaseModel):
    branch_id: UUID
    branch_name: str
    status: str
    sales_available_days: int
    confirmed_zero_sales_days: int
    missing_upload_dates: list[date]
    incomplete_upload_dates: list[date]


class SalesCoverage(BaseModel):
    status: str
    basis: str
    evaluated_branch_days: int
    sales_available_branch_days: int
    confirmed_zero_sales_branch_days: int
    missing_upload_branch_days: int
    incomplete_upload_branch_days: int
    branches: list[SalesBranchCoverage]


class TransactionCountCoverage(BaseModel):
    current: str
    previous: str


class OverviewResponse(BaseModel):
    currency: str
    period: Period
    branch_id: UUID | None
    revenue: MetricComparison
    transaction_count: MetricComparison
    transaction_count_coverage: TransactionCountCoverage
    sales_coverage: SalesCoverage
    active_branches: int
    waste_quantity: Decimal | None
    waste_unit: str | None
    waste_by_unit: list[dict]
    waste_value: MetricComparison
    waste_coverage_status: str
    coverage: Coverage
    unsupported_metrics: list[str]


class SalesTrendPoint(BaseModel):
    period_start: date
    revenue: Decimal


class SalesTrendsResponse(BaseModel):
    currency: str
    grain: str
    period: Period
    current_revenue: Decimal | None
    previous_revenue: Decimal | None
    change_percent: Decimal | None
    points: list[SalesTrendPoint]


class BranchPerformanceRow(BaseModel):
    branch_id: UUID
    branch_name: str
    revenue: Decimal
    previous_revenue: Decimal | None
    change_percent: Decimal | None
    sales_lines: int
    transaction_count: int | None
    transaction_count_coverage_status: str


class BranchPerformanceResponse(BaseModel):
    currency: str
    period: Period
    branches: list[BranchPerformanceRow]
    highest_revenue_branch_id: UUID | None
    lowest_revenue_branch_id: UUID | None


class ProductPerformanceRow(BaseModel):
    product_id: UUID
    sku: str
    product_name: str
    category: str | None
    unit: str
    quantity: Decimal
    revenue: Decimal
    sales_lines: int


class ProductPerformanceResponse(BaseModel):
    currency: str
    period: Period
    top_products: list[ProductPerformanceRow]
    lowest_revenue_products: list[ProductPerformanceRow]
    categories: list[dict]
    product_trends: list[dict]


class InventoryOverviewResponse(BaseModel):
    as_of_date: date
    branch_id: UUID | None
    products: list[dict]
    coverage_status: str
    ingredient_coverage: list[dict]
    expiring_batches: list[dict]
    expired_batches: list[dict]
    reconciliation_discrepancies: list[dict]
    low_stock_thresholds_configured: bool


class WasteOverviewResponse(BaseModel):
    currency: str
    period: Period
    damaged_by_product: list[dict]
    wasted_by_product: list[dict]
    by_branch: list[dict]
    by_unit: list[dict]
    recorded_value: Decimal | None
    cost_coverage_complete: bool
    quantity_coverage_status: str = "UNAVAILABLE"
    snapshot_ledger_reconciliation: str = "NO_OVERLAP"
    trend: list[dict]


class PurchasesOverviewResponse(BaseModel):
    currency: str
    period: Period
    spend: Decimal | None
    receipt_date_coverage_status: str
    missing_receipt_date_lines: int
    priced_lines: int
    total_lines: int
    supplier_purchases: list[dict]
    products: list[dict]
    trend: list[dict]


class AlertResponse(BaseModel):
    id: str
    kind: str
    severity: str
    title: str
    description: str
    branch_id: UUID | None
    product_id: UUID | None = None
    upload_id: UUID | None = None
    href: str


class AlertsResponse(BaseModel):
    as_of_date: date
    alerts: list[AlertResponse]
