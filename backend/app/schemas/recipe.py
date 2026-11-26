from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class RecipeIngredientInput(BaseModel):
    ingredient_product_id: UUID
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=4)
    unit: str = Field(min_length=1, max_length=30)


class ModifierRecipeIngredientInput(BaseModel):
    modifier_option_id: UUID
    ingredient_product_id: UUID
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=4)
    unit: str = Field(min_length=1, max_length=30)


class RecipeVersionCreate(BaseModel):
    effective_from: date
    ingredients: list[RecipeIngredientInput] = Field(min_length=1, max_length=250)
    modifier_ingredients: list[ModifierRecipeIngredientInput] = Field(default_factory=list, max_length=250)


class ModifierGroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    selection_min: int = Field(default=0, ge=0)
    selection_max: int = Field(default=1, ge=1, le=20)
    options: list[str] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def valid_selection_range(self):
        if self.selection_max < self.selection_min:
            raise ValueError("selection_max must be greater than or equal to selection_min")
        normalized = [name.strip().casefold() for name in self.options]
        if any(not name for name in normalized):
            raise ValueError("Modifier option names cannot be empty")
        if len(set(normalized)) != len(normalized):
            raise ValueError("Modifier option names must be unique within the group")
        return self


class ModifierOptionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def non_empty_name(self):
        self.name = self.name.strip()
        if not self.name:
            raise ValueError("Modifier option name cannot be empty")
        return self
