
from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator


class BranchCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    code: str | None = Field(default=None, max_length=30)

    address_line1: str | None = Field(default=None, max_length=255)
    address_line2: str | None = Field(default=None, max_length=255)

    city: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=100)
    postal_code: str | None = Field(default=None, max_length=20)

    country_code: str = Field(min_length=2, max_length=2)
    timezone: str = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("Branch name cannot be empty.")
        return value

    @field_validator("code")
    @classmethod
    def clean_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().upper()
        return value or None

    @field_validator(
        "address_line1",
        "address_line2",
        "city",
        "state",
        "postal_code",
    )
    @classmethod
    def clean_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("country_code")
    @classmethod
    def uppercase_country_code(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        value = value.strip()
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Invalid timezone.")
        return value


class BranchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    company_id: UUID
    name: str
    code: str | None

    address_line1: str | None
    address_line2: str | None
    city: str | None
    state: str | None
    postal_code: str | None

    country_code: str
    timezone: str
    is_active: bool
    created_at: datetime

class BranchMemberAssignRequest(BaseModel):
    company_membership_id: UUID


class BranchMemberResponse(BaseModel):
    id: UUID
    branch_id: UUID
    company_membership_id: UUID
    user_id: UUID
    full_name: str
    email: str
    role: str
    created_at: datetime