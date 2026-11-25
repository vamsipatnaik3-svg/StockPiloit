
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models import Branch, BranchMembership, CompanyMembership, User
from app.schemas.team import EmployeeCreateRequest


class EmployeeEmailAlreadyRegistered(Exception):
    pass


class EmployeeBranchesNotFound(Exception):
    pass


def create_employee(
    db: Session,
    actor: CompanyMembership,
    employee_data: EmployeeCreateRequest,
) -> dict:
    email = str(employee_data.email).strip().lower()

    existing_user = db.scalar(
        select(User).where(User.email == email)
    )

    if existing_user is not None:
        raise EmployeeEmailAlreadyRegistered

    branches = db.scalars(
        select(Branch).where(
            Branch.id.in_(employee_data.branch_ids),
            Branch.company_id == actor.company_id,
            Branch.is_active.is_(True),
        )
    ).all()

    if len(branches) != len(employee_data.branch_ids):
        raise EmployeeBranchesNotFound

    employee = User(
        full_name=employee_data.full_name,
        email=email,
        password_hash=hash_password(employee_data.temporary_password),
        is_active=True,
        must_change_password=True,
    )

    try:
        db.add(employee)
        db.flush()

        company_membership = CompanyMembership(
            company_id=actor.company_id,
            user_id=employee.id,
            role=employee_data.role,
        )
        db.add(company_membership)
        db.flush()

        assignments = [
            BranchMembership(
                branch_id=branch.id,
                company_membership_id=company_membership.id,
            )
            for branch in branches
        ]

        db.add_all(assignments)
        db.commit()

        return {
            "user_id": employee.id,
            "membership_id": company_membership.id,
            "full_name": employee.full_name,
            "email": employee.email,
            "role": company_membership.role,
            "branch_ids": [branch.id for branch in branches],
            "must_change_password": employee.must_change_password,
        }

    except IntegrityError:
        db.rollback()

        existing_user = db.scalar(
            select(User).where(User.email == email)
        )

        if existing_user is not None:
            raise EmployeeEmailAlreadyRegistered

        raise

    except Exception:
        db.rollback()
        raise
