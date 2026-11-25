
from uuid import UUID

from fastapi import Cookie, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import CompanyMembership, User
from app.services.authentication import get_authenticated_user


VALID_ROLES = {
    "OWNER",
    "MANAGER",
    "STAFF",
    "ANALYST",
}


def get_current_user(
    stockpilot_session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> User:
    """Return the user associated with the current valid session."""

    if not stockpilot_session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )

    user = get_authenticated_user(db, stockpilot_session)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session.",
        )

    return user


def _resolve_current_membership(
    user: User,
    db: Session,
    company_id: UUID | None,
) -> CompanyMembership:
    """Resolve the authenticated user's membership in a company."""

    query = select(CompanyMembership).where(
        CompanyMembership.user_id == user.id
    )

    if company_id is not None:
        query = query.where(
            CompanyMembership.company_id == company_id
        )

        membership = db.scalar(query)

        if membership is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to this company.",
            )

        return membership

    memberships = db.scalars(query).all()

    if not memberships:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not belong to any company.",
        )

    if len(memberships) > 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Multiple company memberships found. Please select a company.",
        )

    return memberships[0]


def get_current_membership_for_account(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    company_id: UUID | None = Header(default=None, alias="X-Company-ID"),
) -> CompanyMembership:
    """
    Resolve membership for account-level endpoints.

    This intentionally allows users who must change their password
    to retrieve essential account information.
    """

    return _resolve_current_membership(
        user=user,
        db=db,
        company_id=company_id,
    )


def get_current_membership(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    company_id: UUID | None = Header(default=None, alias="X-Company-ID"),
) -> CompanyMembership:
    """
    Resolve membership for normal business endpoints.

    Users with temporary passwords must change their password first.
    """

    if user.must_change_password:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "PASSWORD_CHANGE_REQUIRED",
                "message": "You must change your password before accessing this resource.",
            },
        )

    return _resolve_current_membership(
        user=user,
        db=db,
        company_id=company_id,
    )


def require_roles(*allowed_roles: str):
    """Create a dependency that allows only specified membership roles."""

    if not allowed_roles:
        raise ValueError("At least one allowed role must be provided.")

    invalid_roles = set(allowed_roles) - VALID_ROLES

    if invalid_roles:
        raise ValueError(
            f"Invalid roles provided: {sorted(invalid_roles)}"
        )

    def role_checker(
        membership: CompanyMembership = Depends(get_current_membership),
    ) -> CompanyMembership:

        if membership.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action.",
            )

        return membership

    return role_checker
