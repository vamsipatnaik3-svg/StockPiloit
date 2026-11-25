
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Branch,
    BranchMembership,
    CompanyMembership,
    User,
)
from app.schemas.branch import BranchCreateRequest


class BranchNotFoundError(Exception):
    pass


class CompanyMembershipNotFoundError(Exception):
    pass


class DuplicateBranchMembershipError(Exception):
    pass


class BranchMemberNotFoundError(Exception):
    pass


class BranchAccessDeniedError(Exception):
    pass


def create_branch(
    db: Session,
    membership: CompanyMembership,
    branch_data: BranchCreateRequest,
) -> Branch:
    branch = Branch(
        company_id=membership.company_id,
        name=branch_data.name,
        code=branch_data.code,
        address_line1=branch_data.address_line1,
        address_line2=branch_data.address_line2,
        city=branch_data.city,
        state=branch_data.state,
        postal_code=branch_data.postal_code,
        country_code=branch_data.country_code,
        timezone=branch_data.timezone,
    )

    db.add(branch)
    db.commit()
    db.refresh(branch)

    return branch



def get_company_branches(
    db: Session,
    membership: CompanyMembership,
) -> list[Branch]:
    query = select(Branch).where(
        Branch.company_id == membership.company_id
    )

    if membership.role != "OWNER":
        query = (
            query
            .join(
                BranchMembership,
                BranchMembership.branch_id == Branch.id,
            )
            .where(
                BranchMembership.company_membership_id == membership.id,
                Branch.is_active.is_(True),
            )
        )

    query = query.order_by(Branch.name.asc())

    return list(db.scalars(query).all())




def get_company_branch(
    db: Session,
    membership: CompanyMembership,
    branch_id: UUID,
) -> Branch:
    branch = db.scalar(
        select(Branch).where(
            Branch.id == branch_id,
            Branch.company_id == membership.company_id,
        )
    )

    if branch is None:
        raise BranchNotFoundError

    if membership.role != "OWNER" and not branch.is_active:
        raise BranchNotFoundError

    return branch


def _get_branch_member_response(
    db: Session,
    branch_membership: BranchMembership,
) -> dict:
    result = db.execute(
        select(
            BranchMembership,
            CompanyMembership,
            User,
        )
        .join(
            CompanyMembership,
            CompanyMembership.id
            == BranchMembership.company_membership_id,
        )
        .join(
            User,
            User.id == CompanyMembership.user_id,
        )
        .where(
            BranchMembership.id == branch_membership.id
        )
    ).one()

    assignment, company_membership, user = result

    return {
        "id": assignment.id,
        "branch_id": assignment.branch_id,
        "company_membership_id": company_membership.id,
        "user_id": user.id,
        "full_name": user.full_name,
        "email": user.email,
        "role": company_membership.role,
        "created_at": assignment.created_at,
    }


def assign_branch_member(
    db: Session,
    actor: CompanyMembership,
    branch_id: UUID,
    target_membership_id: UUID,
) -> dict:
    branch = get_company_branch(db, actor, branch_id)

    target_membership = db.scalar(
        select(CompanyMembership).where(
            CompanyMembership.id == target_membership_id,
            CompanyMembership.company_id == actor.company_id,
        )
    )

    if target_membership is None:
        raise CompanyMembershipNotFoundError

    existing_assignment = db.scalar(
        select(BranchMembership).where(
            BranchMembership.branch_id == branch.id,
            BranchMembership.company_membership_id
            == target_membership.id,
        )
    )

    if existing_assignment is not None:
        raise DuplicateBranchMembershipError

    assignment = BranchMembership(
        branch_id=branch.id,
        company_membership_id=target_membership.id,
    )

    db.add(assignment)

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(assignment)

    return _get_branch_member_response(db, assignment)


def get_branch_members(
    db: Session,
    actor: CompanyMembership,
    branch_id: UUID,
) -> list[dict]:
    branch = get_company_branch(db, actor, branch_id)

    if actor.role != "OWNER":
        actor_assignment = db.scalar(
            select(BranchMembership).where(
                BranchMembership.branch_id == branch.id,
                BranchMembership.company_membership_id == actor.id,
            )
        )

        if actor_assignment is None:
            raise BranchAccessDeniedError

    results = db.execute(
        select(
            BranchMembership,
            CompanyMembership,
            User,
        )
        .join(
            CompanyMembership,
            CompanyMembership.id
            == BranchMembership.company_membership_id,
        )
        .join(
            User,
            User.id == CompanyMembership.user_id,
        )
        .where(
            BranchMembership.branch_id == branch.id
        )
        .order_by(User.full_name.asc())
    ).all()

    return [
        {
            "id": assignment.id,
            "branch_id": assignment.branch_id,
            "company_membership_id": company_membership.id,
            "user_id": user.id,
            "full_name": user.full_name,
            "email": user.email,
            "role": company_membership.role,
            "created_at": assignment.created_at,
        }
        for assignment, company_membership, user in results
    ]


def remove_branch_member(
    db: Session,
    actor: CompanyMembership,
    branch_id: UUID,
    target_membership_id: UUID,
) -> None:
    branch = get_company_branch(db, actor, branch_id)

    assignment = db.scalar(
        select(BranchMembership).where(
            BranchMembership.branch_id == branch.id,
            BranchMembership.company_membership_id
            == target_membership_id,
        )
    )

    if assignment is None:
        raise BranchMemberNotFoundError

    db.delete(assignment)
    db.commit()

def get_eligible_company_members(
    db: Session,
    membership: CompanyMembership,
) -> list[dict]:
    results = db.execute(
        select(CompanyMembership, User)
        .join(
            User,
            User.id == CompanyMembership.user_id,
        )
        .where(
            CompanyMembership.company_id == membership.company_id,
            User.is_active.is_(True),
        )
        .order_by(
            User.full_name.asc(),
            User.email.asc(),
        )
    ).all()

    return [
        {
            "membership_id": company_membership.id,
            "user_id": user.id,
            "full_name": user.full_name,
            "email": user.email,
            "role": company_membership.role,
        }
        for company_membership, user in results
    ]