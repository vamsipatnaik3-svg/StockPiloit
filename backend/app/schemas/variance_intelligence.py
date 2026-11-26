from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class BaselineComparisonPeriod(BaseModel):
    """A complete historical window that contributed to a finding's baseline."""

    start_date: date = Field(description="Inclusive start of the historical comparison window.")
    end_date: date = Field(description="Inclusive end of the historical comparison window.")


class VarianceFinding(BaseModel):
    id: str
    finding_type: str
    status: Literal["ANOMALY", "NORMAL", "INSUFFICIENT_BASELINE", "INCOMPLETE_DATA", "UNAVAILABLE"]
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] | None
    confidence: Literal["LOW", "MEDIUM", "HIGH"]
    company_id: UUID
    branch_id: UUID | None
    branch_name: str | None
    ingredient_id: UUID
    ingredient_sku: str
    ingredient_name: str
    unit: str
    start_date: date
    end_date: date
    metric_value: Decimal | None
    metric_unit: str
    baseline_value: Decimal | None
    absolute_difference: Decimal | None
    percentage_difference: Decimal | None
    direction: str | None = None
    baseline_periods: int
    baseline_comparison_periods: list[BaselineComparisonPeriod] = Field(
        default_factory=list,
        description=("Historical windows whose eligible metric values contributed to the baseline. "
            "Empty when no usable historical baseline was formed. The current analysis window "
            "is reported separately by start_date and end_date."),
    )
    data_status: str
    reason_codes: list[str]
    evidence: dict
    explanation: str
    recommendation: str | None


class VarianceIntelligenceResponse(BaseModel):
    start_date: date
    end_date: date
    branch_id: UUID | None
    ingredient_id: UUID | None
    finding_type: str | None
    severity: str | None
    status: str | None
    total: int
    offset: int
    limit: int
    findings: list[VarianceFinding]
    limitations: list[str]

