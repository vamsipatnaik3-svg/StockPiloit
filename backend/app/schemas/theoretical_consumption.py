from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


CalculationStatus = Literal["COMPLETE", "INCOMPLETE", "UNAVAILABLE", "UNIT_MISMATCH", "INVALID_DATA"]


class SourceUploadReference(BaseModel):
    upload_id: UUID
    version: int


class TheoreticalConsumptionItem(BaseModel):
    company_id: UUID
    branch_id: UUID
    branch_name: str
    business_date: date
    ingredient_id: UUID
    ingredient_sku: str
    ingredient_name: str
    canonical_unit: str
    base_theoretical_consumption: Decimal | None
    modifier_theoretical_consumption: Decimal | None
    total_theoretical_consumption: Decimal | None
    status: CalculationStatus
    reason_codes: list[str]
    source_uploads: list[SourceUploadReference]


class TheoreticalConsumptionScope(BaseModel):
    company_id: UUID
    branch_id: UUID
    branch_name: str
    business_date: date
    status: CalculationStatus
    reason_codes: list[str]
    source_uploads: list[SourceUploadReference]


class UnresolvedTheoreticalSale(BaseModel):
    sales_record_id: UUID
    branch_id: UUID
    business_date: date
    reason_codes: list[str]
    source_upload_id: UUID
    source_upload_version: int


class TheoreticalConsumptionResponse(BaseModel):
    start_date: date
    end_date: date
    branch_id: UUID | None
    ingredient_id: UUID | None
    items: list[TheoreticalConsumptionItem]
    scopes: list[TheoreticalConsumptionScope]
    unresolved_sales: list[UnresolvedTheoreticalSale]
