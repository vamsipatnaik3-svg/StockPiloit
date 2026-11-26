from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.schemas.theoretical_consumption import CalculationStatus, SourceUploadReference


class ActualConsumptionItem(BaseModel):
    company_id: UUID
    branch_id: UUID | None
    branch_name: str | None
    ingredient_id: UUID
    ingredient_sku: str
    ingredient_name: str
    canonical_unit: str
    opening_stock: Decimal | None
    closing_stock: Decimal | None
    total_inflows: Decimal | None
    total_outflows: Decimal | None
    actual_stock_depletion: Decimal | None
    known_non_sales_outflows: Decimal | None
    actual_sales_related_consumption: Decimal | None
    theoretical_consumption: Decimal | None
    absolute_variance: Decimal | None
    variance_percent: Decimal | None
    status: CalculationStatus
    theoretical_status: CalculationStatus
    comparison_status: CalculationStatus
    reason_codes: list[str]
    theoretical_reason_codes: list[str]
    source_uploads: list[SourceUploadReference]


class ActualConsumptionResponse(BaseModel):
    start_date: date
    end_date: date
    branch_id: UUID | None
    ingredient_id: UUID | None
    items: list[ActualConsumptionItem]
    company_totals: list[ActualConsumptionItem]
