from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ManualMovementType = Literal[
    "OTHER_INFLOW", "POSITIVE_ADJUSTMENT", "WASTE", "STAFF_CONSUMPTION",
    "DAMAGE", "NEGATIVE_ADJUSTMENT", "OTHER_OUTFLOW",
]
MovementType = Literal[
    "PURCHASE_RECEIPT", "OTHER_INFLOW", "POSITIVE_ADJUSTMENT", "TRANSFER_IN",
    "WASTE", "STAFF_CONSUMPTION", "DAMAGE", "NEGATIVE_ADJUSTMENT",
    "OTHER_OUTFLOW", "TRANSFER_OUT",
]


class ManualMovementCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    branch_id: UUID
    ingredient_product_id: UUID
    movement_type: ManualMovementType
    movement_date: date
    quantity: Decimal = Field(gt=Decimal("0"), max_digits=18, decimal_places=4)
    unit: str = Field(min_length=1, max_length=30)
    batch_number: str | None = Field(default=None, max_length=120)
    reason_code: str = Field(min_length=1, max_length=60)
    reason_detail: str | None = Field(default=None, max_length=500)
    source_reference: str | None = Field(default=None, max_length=150)

    @field_validator("unit", "reason_code")
    @classmethod
    def strip_required_strings(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("This field cannot be blank.")
        return value

    @field_validator("batch_number", "reason_detail", "source_reference")
    @classmethod
    def strip_optional_strings(cls, value: str | None) -> str | None:
        value = value.strip() if value is not None else None
        return value or None

    @model_validator(mode="after")
    def require_detail_when_needed(self):
        uses_detail = (
            self.movement_type in {"POSITIVE_ADJUSTMENT", "NEGATIVE_ADJUSTMENT"}
            or self.reason_code.startswith("OTHER_")
            or self.reason_code.endswith("_OTHER")
        )
        if uses_detail and not self.reason_detail:
            raise ValueError("Reason detail is required for adjustments and 'other' reason codes.")
        return self


class ManualMovementVoid(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("A void reason is required.")
        return value


class StockMovementResponse(BaseModel):
    id: UUID
    company_id: UUID
    branch_id: UUID
    branch_name: str
    ingredient_product_id: UUID
    ingredient_sku: str
    ingredient_name: str
    movement_type: MovementType
    direction: Literal["INFLOW", "OUTFLOW"]
    movement_date: date
    occurred_at: datetime | None
    quantity: Decimal
    unit: str
    batch_number: str | None
    origin_type: Literal["UPLOAD", "MANUAL"]
    source_upload_id: UUID | None
    purchase_line_id: UUID | None
    transfer_id: UUID | None
    source_reference: str | None
    reason_code: str | None
    reason_label: str | None
    reason_detail: str | None
    created_by_user_id: UUID | None
    created_by_name: str | None
    created_at: datetime
    voided_by_user_id: UUID | None
    voided_by_name: str | None
    voided_at: datetime | None
    void_reason: str | None

    model_config = ConfigDict(from_attributes=True)


class StockMovementListResponse(BaseModel):
    items: list[StockMovementResponse]
    total: int
    limit: int
    offset: int
