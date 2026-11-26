from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (AnalystAnalyticsGrant, AnalystAnalyticsGrantBranch,
    Branch, CompanyMembership)
from app.schemas.analyst_analytics_grant import AnalystAnalyticsGrantCreate


def _require_owner(owner: CompanyMembership) -> None:
    # Keep the service safe if called outside its HTTP route.
    if owner.role != "OWNER":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an owner can manage Analyst analytics access.")


def _view(db: Session, grant: AnalystAnalyticsGrant) -> dict:
    branch_ids = db.scalars(select(AnalystAnalyticsGrantBranch.branch_id).where(
        AnalystAnalyticsGrantBranch.grant_id == grant.id,
        AnalystAnalyticsGrantBranch.company_id == grant.company_id,
    ).order_by(AnalystAnalyticsGrantBranch.branch_id)).all()
    return {
        "id": grant.id,
        "company_id": grant.company_id,
        "analyst_membership_id": grant.analyst_membership_id,
        "granted_by_membership_id": grant.granted_by_membership_id,
        "scope_type": grant.scope_type,
        "branch_ids": list(branch_ids),
        "created_at": grant.created_at,
        "revoked_at": grant.revoked_at,
        "revoked_by_membership_id": grant.revoked_by_membership_id,
    }


def create_grant(db: Session, owner: CompanyMembership,
                 data: AnalystAnalyticsGrantCreate) -> dict:
    _require_owner(owner)
    target = db.scalar(select(CompanyMembership).where(
        CompanyMembership.id == data.analyst_membership_id,
        CompanyMembership.company_id == owner.company_id,
    ))
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
            detail="Analyst membership not found.")
    if target.role != "ANALYST":
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Access grants can only be created for an Analyst membership.")

    branches = []
    if data.scope_type == "BRANCHES":
        branches = db.scalars(select(Branch).where(
            Branch.company_id == owner.company_id,
            Branch.id.in_(data.branch_ids),
            Branch.is_active.is_(True),
        )).all()
        if len(branches) != len(data.branch_ids):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                detail="One or more branches were not found or are inactive.")

    grant = AnalystAnalyticsGrant(
        company_id=owner.company_id,
        analyst_membership_id=target.id,
        granted_by_membership_id=owner.id,
        scope_type=data.scope_type,
    )
    db.add(grant)
    try:
        db.flush()
        db.add_all(AnalystAnalyticsGrantBranch(
            grant_id=grant.id, company_id=owner.company_id, branch_id=branch.id,
        ) for branch in branches)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
            detail="An active analytics grant already exists for this Analyst.")
    db.refresh(grant)
    return _view(db, grant)


def list_grants(db: Session, owner: CompanyMembership) -> list[dict]:
    _require_owner(owner)
    grants = db.scalars(select(AnalystAnalyticsGrant).where(
        AnalystAnalyticsGrant.company_id == owner.company_id,
    ).order_by(AnalystAnalyticsGrant.created_at.desc(), AnalystAnalyticsGrant.id)).all()
    return [_view(db, grant) for grant in grants]


def get_grant(db: Session, owner: CompanyMembership, grant_id: UUID) -> dict:
    _require_owner(owner)
    grant = db.scalar(select(AnalystAnalyticsGrant).where(
        AnalystAnalyticsGrant.id == grant_id,
        AnalystAnalyticsGrant.company_id == owner.company_id,
    ))
    if grant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
            detail="Analytics grant not found.")
    return _view(db, grant)


def revoke_grant(db: Session, owner: CompanyMembership, grant_id: UUID) -> dict:
    _require_owner(owner)
    grant = db.scalar(select(AnalystAnalyticsGrant).where(
        AnalystAnalyticsGrant.id == grant_id,
        AnalystAnalyticsGrant.company_id == owner.company_id,
    ).with_for_update())
    if grant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
            detail="Analytics grant not found.")
    if grant.revoked_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
            detail="Analytics grant has already been revoked.")
    grant.revoked_at = datetime.now(timezone.utc)
    grant.revoked_by_membership_id = owner.id
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
            detail="Analytics grant could not be revoked.")
    db.refresh(grant)
    return _view(db, grant)
