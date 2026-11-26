from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StockCountLineCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ingredient_product_id: UUID
    quantity: Decimal = Field(ge=Decimal("0"), max_digits=18, decimal_places=4)
    unit: str = Field(min_length=1, max_length=30)
    batch_number: str | None = Field(default=None, max_length=120)

    @field_validator("unit")
    @classmethod
    def normalize_unit(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Unit cannot be blank.")
        return value

    @field_validator("batch_number")
    @classmethod
    def normalize_batch(cls, value: str | None) -> str | None:
        value = value.strip() if value is not None else None
        return value or None


class StockCountCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    branch_id: UUID
    counted_at: datetime
    idempotency_key: UUID
    corrects_submission_id: UUID | None = None
    lines: list[StockCountLineCreate] = Field(min_length=1, max_length=500)

    @field_validator("counted_at")
    @classmethod
    def require_aware_count_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("counted_at must include a timezone offset.")
        return value

    @model_validator(mode="after")
    def unique_ingredient_batches(self):
        keys = [(line.ingredient_product_id, line.batch_number or "") for line in self.lines]
        if len(keys) != len(set(keys)):
            raise ValueError("An ingredient and batch may appear only once per submission.")
        return self


class StockCountLineResponse(BaseModel):
    id: UUID
    ingredient_product_id: UUID
    sku: str
    ingredient_name: str
    quantity: Decimal
    unit: str
    batch_number: str | None


class StockCountResponse(BaseModel):
    id: UUID
    company_id: UUID
    branch_id: UUID
    branch_name: str
    submitted_by_membership_id: UUID
    submitted_by_name: str
    counted_at: datetime
    submitted_at: datetime
    status: Literal["SUBMITTED"]
    corrects_submission_id: UUID | None
    lines: list[StockCountLineResponse]


class StockCountListResponse(BaseModel):
    items: list[StockCountResponse]
    total: int
    limit: int
    offset: int


class WasteDamageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    branch_id: UUID
    ingredient_product_id: UUID
    movement_type: Literal["WASTE", "DAMAGE"]
    occurred_at: datetime
    idempotency_key: UUID
    quantity: Decimal = Field(gt=Decimal("0"), max_digits=18, decimal_places=4)
    unit: str = Field(min_length=1, max_length=30)
    batch_number: str | None = Field(default=None, max_length=120)
    reason_code: str = Field(min_length=1, max_length=60)
    notes: str | None = Field(default=None, max_length=500)

    @field_validator("occurred_at")
    @classmethod
    def require_aware_event_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must include a timezone offset.")
        return value

    @field_validator("unit", "reason_code")
    @classmethod
    def normalize_required_strings(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("This field cannot be blank.")
        return value

    @field_validator("batch_number", "notes")
    @classmethod
    def normalize_optional_strings(cls, value: str | None) -> str | None:
        value = value.strip() if value is not None else None
        return value or None


class ReceiptConfirmationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: UUID


class ReceiptConfirmationResponse(BaseModel):
    id: UUID
    company_id: UUID
    branch_id: UUID
    branch_name: str
    receipt_identity_id: UUID
    purchase_line_id: UUID
    receipt_event_id: str
    ingredient_product_id: UUID
    ingredient_sku: str
    ingredient_name: str
    quantity_confirmed: Decimal
    unit: str
    confirmed_by_membership_id: UUID
    confirmed_by_name: str
    confirmed_at: datetime


class ReceiptConfirmationListResponse(BaseModel):
    items: list[ReceiptConfirmationResponse]
    total: int
    limit: int
    offset: int


class ConfirmableReceiptResponse(BaseModel):
    receipt_identity_id: UUID
    receipt_event_id: str
    purchase_line_id: UUID
    branch_id: UUID
    receipt_date: date
    ingredient_product_id: UUID
    ingredient_sku: str
    ingredient_name: str
    quantity_received: Decimal
    unit: str
    batch_number: str | None
    confirmation_id: UUID | None


class ConfirmableReceiptListResponse(BaseModel):
    items: list[ConfirmableReceiptResponse]
    total: int
    limit: int
    offset: int
