
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_membership, require_roles
from app.db.session import get_db
from app.models import CompanyMembership
from app.schemas.branch import (
    BranchCreateRequest,
    BranchMemberAssignRequest,
    BranchMemberResponse,
    BranchResponse,
    EligibleCompanyMemberResponse,
)
from app.services.branches import (
    BranchAccessDeniedError,
    BranchMemberNotFoundError,
    BranchNotFoundError,
    CompanyMembershipNotFoundError,
    DuplicateBranchMembershipError,
    assign_branch_member,
    create_branch,
    get_branch_members,
    get_company_branches,
    get_eligible_company_members,
    remove_branch_member,
)


router = APIRouter(tags=["Branches"])

@router.get(
    "/members/eligible",
    response_model=list[EligibleCompanyMemberResponse],
    status_code=status.HTTP_200_OK,
)
def list_eligible_company_members_endpoint(
    membership: CompanyMembership = Depends(require_roles("OWNER")),
    db: Session = Depends(get_db),
):
    try:
        return get_eligible_company_members(
            db=db,
            membership=membership,
        )

    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to retrieve company members.",
        )

@router.post(
    "",
    response_model=BranchResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_branch_endpoint(
    branch_data: BranchCreateRequest,
    membership: CompanyMembership = Depends(require_roles("OWNER")),
    db: Session = Depends(get_db),
):
    try:
        return create_branch(
            db=db,
            membership=membership,
            branch_data=branch_data,
        )

    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A branch with this name or code already exists.",
        )

    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to create branch.",
        )


@router.get(
    "",
    response_model=list[BranchResponse],
    status_code=status.HTTP_200_OK,
)
def list_branches_endpoint(
    membership: CompanyMembership = Depends(get_current_membership),
    db: Session = Depends(get_db),
):
    try:
        return get_company_branches(
            db=db,
            membership=membership,
        )

    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to retrieve branches.",
        )


@router.post(
    "/{branch_id}/members",
    response_model=BranchMemberResponse,
    status_code=status.HTTP_201_CREATED,
)
def assign_branch_member_endpoint(
    branch_id: UUID,
    request: BranchMemberAssignRequest,
    membership: CompanyMembership = Depends(require_roles("OWNER")),
    db: Session = Depends(get_db),
):
    try:
        return assign_branch_member(
            db=db,
            actor=membership,
            branch_id=branch_id,
            target_membership_id=request.company_membership_id,
        )

    except BranchNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Branch not found.",
        )

    except CompanyMembershipNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company membership not found.",
        )

    except DuplicateBranchMembershipError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This member is already assigned to the branch.",
        )

    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This member is already assigned to the branch.",
        )

    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to assign branch member.",
        )


@router.get(
    "/{branch_id}/members",
    response_model=list[BranchMemberResponse],
    status_code=status.HTTP_200_OK,
)
def list_branch_members_endpoint(
    branch_id: UUID,
    membership: CompanyMembership = Depends(get_current_membership),
    db: Session = Depends(get_db),
):
    try:
        return get_branch_members(
            db=db,
            actor=membership,
            branch_id=branch_id,
        )

    except BranchNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Branch not found.",
        )

    except BranchAccessDeniedError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this branch.",
        )

    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to retrieve branch members.",
        )


@router.delete(
    "/{branch_id}/members/{membership_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_branch_member_endpoint(
    branch_id: UUID,
    membership_id: UUID,
    membership: CompanyMembership = Depends(require_roles("OWNER")),
    db: Session = Depends(get_db),
):
    try:
        remove_branch_member(
            db=db,
            actor=membership,
            branch_id=branch_id,
            target_membership_id=membership_id,
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    except BranchNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Branch not found.",
        )

    except BranchMemberNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Member assignment not found.",
        )

    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to remove branch member.",
        )
