from uuid import UUID

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ProductKind = Literal["MENU_ITEM", "INGREDIENT", "LEGACY"]


class ProductCreate(BaseModel):
    sku: str = Field(min_length=1, max_length=100)
    product_name: str = Field(min_length=1, max_length=200)
    category_id: UUID | None = None
    brand: str | None = Field(default=None, max_length=100)
    unit_of_measure: str = Field(min_length=1, max_length=30)
    barcode: str | None = Field(default=None, max_length=100)
    product_kind: ProductKind = "LEGACY"


class ProductUpdate(BaseModel):
    sku: str | None = Field(default=None, min_length=1, max_length=100)
    product_name: str | None = Field(default=None, min_length=1, max_length=200)
    category_id: UUID | None = None
    brand: str | None = Field(default=None, max_length=100)
    unit_of_measure: str | None = Field(default=None, min_length=1, max_length=30)
    barcode: str | None = Field(default=None, max_length=100)
    is_active: bool | None = None
    product_kind: ProductKind = "LEGACY"


class ProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    category_id: UUID | None
    sku: str
    product_name: str
    brand: str | None
    unit_of_measure: str
    barcode: str | None
    is_active: bool
    product_kind: ProductKind


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class CategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
