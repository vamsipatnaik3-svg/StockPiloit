from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


GrantScopeType = Literal["COMPANY", "BRANCHES"]


class AnalystAnalyticsGrantCreate(BaseModel):
    analyst_membership_id: UUID
    scope_type: GrantScopeType
    branch_ids: list[UUID] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_scope(self):
        if self.scope_type == "COMPANY" and self.branch_ids:
            raise ValueError("Company-wide grants cannot include branch IDs.")
        if self.scope_type == "BRANCHES" and not self.branch_ids:
            raise ValueError("Selected-branch grants require at least one branch.")
        if len(self.branch_ids) != len(set(self.branch_ids)):
            raise ValueError("Duplicate branch IDs are not allowed.")
        return self


class AnalystAnalyticsGrantResponse(BaseModel):
    id: UUID
    company_id: UUID
    analyst_membership_id: UUID
    granted_by_membership_id: UUID
    scope_type: GrantScopeType
    branch_ids: list[UUID]
    created_at: datetime
    revoked_at: datetime | None
    revoked_by_membership_id: UUID | None


class AnalystAnalyticsGrantListResponse(BaseModel):
    items: list[AnalystAnalyticsGrantResponse]
    total: int
