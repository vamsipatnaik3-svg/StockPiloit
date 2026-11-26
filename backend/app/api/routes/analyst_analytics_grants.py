from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.dependencies import require_roles
from app.db.session import get_db
from app.models import CompanyMembership
from app.schemas.analyst_analytics_grant import (
    AnalystAnalyticsGrantCreate,
    AnalystAnalyticsGrantListResponse,
    AnalystAnalyticsGrantResponse,
)
from app.services.analyst_analytics_grants import (
    create_grant,
    get_grant,
    list_grants,
    revoke_grant,
)


router = APIRouter(tags=["Analyst Analytics Access"])


@router.post("", response_model=AnalystAnalyticsGrantResponse,
             status_code=status.HTTP_201_CREATED)
def create_analyst_analytics_grant(
    data: AnalystAnalyticsGrantCreate,
    owner: CompanyMembership = Depends(require_roles("OWNER")),
    db: Session = Depends(get_db),
):
    return create_grant(db, owner, data)


@router.get("", response_model=AnalystAnalyticsGrantListResponse)
def list_analyst_analytics_grants(
    owner: CompanyMembership = Depends(require_roles("OWNER")),
    db: Session = Depends(get_db),
):
    items = list_grants(db, owner)
    return {"items": items, "total": len(items)}


@router.get("/{grant_id}", response_model=AnalystAnalyticsGrantResponse)
def get_analyst_analytics_grant(
    grant_id: UUID,
    owner: CompanyMembership = Depends(require_roles("OWNER")),
    db: Session = Depends(get_db),
):
    return get_grant(db, owner, grant_id)


@router.post("/{grant_id}/revoke", response_model=AnalystAnalyticsGrantResponse)
def revoke_analyst_analytics_grant(
    grant_id: UUID,
    owner: CompanyMembership = Depends(require_roles("OWNER")),
    db: Session = Depends(get_db),
):
    return revoke_grant(db, owner, grant_id)
