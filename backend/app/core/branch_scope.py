from dataclasses import dataclass
from typing import Sequence
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (AnalystAnalyticsGrant, AnalystAnalyticsGrantBranch,
    Branch, BranchMembership, CompanyMembership)


@dataclass(frozen=True)
class BranchAccessScope:
    """Resolved tenant and branch authorization; safe to pass to query services."""

    company_id: UUID
    membership_id: UUID
    role: str
    branch_ids: frozenset[UUID]
    scope_type: str
    grant_id: UUID | None = None

    def contains(self, branch_id: UUID) -> bool:
        return branch_id in self.branch_ids

    def criteria(self, company_column, branch_column):
        """SQL predicates that must be applied before aggregation/grouping."""
        return (company_column == self.company_id,
                branch_column.in_(self.branch_ids))


def resolve_branch_scope(db: Session, membership: CompanyMembership,
                         requested_branch_ids: Sequence[UUID] | None = None
                         ) -> BranchAccessScope:
    """Resolve permitted branches without treating an omitted filter as all.

    OWNER is company-scoped. MANAGER and STAFF receive assigned active branches.
    ANALYST receives exactly one active explicit grant. This helper grants no
    endpoint capability: routes must separately decide whether the role may
    perform the requested read or write.
    """
    grant_id = None
    scope_type = "BRANCH_SET"
    if membership.role == "OWNER":
        allowed = set(db.scalars(select(Branch.id).where(
            Branch.company_id == membership.company_id)).all())
        scope_type = "COMPANY"
    elif membership.role in {"MANAGER", "STAFF"}:
        allowed = set(db.scalars(select(Branch.id).join(
            BranchMembership, BranchMembership.branch_id == Branch.id,
        ).where(
            Branch.company_id == membership.company_id,
            Branch.is_active.is_(True),
            BranchMembership.company_membership_id == membership.id,
        )).all())
    elif membership.role == "ANALYST":
        grant = db.scalar(select(AnalystAnalyticsGrant).where(
            AnalystAnalyticsGrant.company_id == membership.company_id,
            AnalystAnalyticsGrant.analyst_membership_id == membership.id,
            AnalystAnalyticsGrant.revoked_at.is_(None),
        ))
        if grant is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                detail="No active analytics access grant exists.")
        grant_id = grant.id
        scope_type = grant.scope_type
        if grant.scope_type == "COMPANY":
            allowed = set(db.scalars(select(Branch.id).where(
                Branch.company_id == membership.company_id,
                Branch.is_active.is_(True),
            )).all())
        else:
            allowed = set(db.scalars(select(AnalystAnalyticsGrantBranch.branch_id).join(
                Branch, (Branch.id == AnalystAnalyticsGrantBranch.branch_id)
                & (Branch.company_id == AnalystAnalyticsGrantBranch.company_id),
            ).where(
                AnalystAnalyticsGrantBranch.grant_id == grant.id,
                AnalystAnalyticsGrantBranch.company_id == membership.company_id,
                Branch.is_active.is_(True),
            )).all())
    else:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have branch access.")

    if not allowed and membership.role != "OWNER":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
            detail="No active branches are available in your access scope.")

    if requested_branch_ids is None:
        resolved = allowed
    else:
        requested = list(requested_branch_ids)
        if not requested:
            raise HTTPException(status_code=422,
                detail="At least one branch ID must be provided.")
        if len(requested) != len(set(requested)):
            raise HTTPException(status_code=422,
                detail="Duplicate branch IDs are not allowed.")
        if not set(requested).issubset(allowed):
            # Do not disclose whether a foreign/unassigned branch exists.
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                detail="Branch not found or not accessible.")
        resolved = set(requested)

    return BranchAccessScope(
        company_id=membership.company_id,
        membership_id=membership.id,
        role=membership.role,
        branch_ids=frozenset(resolved),
        scope_type=scope_type,
        grant_id=grant_id,
    )
