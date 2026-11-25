from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, EmailStr, Field, field_validator


Industry = Literal[
    "grocery",
    "pharmacy",
    "fashion",
    "electronics",
    "general_retail",
    "other",
]


class RegistrationRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=150)
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)

    company_name: str = Field(min_length=2, max_length=150)
    industry: Industry

    country_code: str = Field(min_length=2, max_length=2)
    currency: str = Field(min_length=3, max_length=3)
    timezone: str = Field(min_length=1, max_length=100)

    @field_validator("full_name", "company_name")
    @classmethod
    def clean_names(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("This field cannot be empty")
        return value

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()

    @field_validator("country_code", "currency")
    @classmethod
    def uppercase_codes(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        value = value.strip()
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Invalid timezone")
        return value


class RegistrationResponse(BaseModel):
    user_id: str
    company_id: str
    company_name: str
    user_email: EmailStr
    role: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_login_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()


class LoginResponse(BaseModel):
    user_id: str
    full_name: str
    email: EmailStr
