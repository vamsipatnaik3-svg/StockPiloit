
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator


EmployeeRole = Literal["MANAGER", "STAFF", "ANALYST"]


class EmployeeCreateRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=150)
    email: EmailStr
    temporary_password: str = Field(min_length=12, max_length=128)
    role: EmployeeRole
    branch_ids: list[UUID] = Field(min_length=1)

    @field_validator("full_name")
    @classmethod
    def clean_full_name(cls, value: str) -> str:
        value = " ".join(value.split())

        if not value:
            raise ValueError("Employee name cannot be empty.")

        return value

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()

    @field_validator("branch_ids")
    @classmethod
    def validate_branch_ids(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("Duplicate branch IDs are not allowed.")

        return value


class EmployeeCreateResponse(BaseModel):
    user_id: UUID
    membership_id: UUID
    full_name: str
    email: EmailStr
    role: EmployeeRole
    branch_ids: list[UUID]
    must_change_password: bool
