
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.dependencies import require_roles
from app.db.session import get_db
from app.models import CompanyMembership
from app.schemas.team import (
    EmployeeCreateRequest,
    EmployeeCreateResponse,
)
from app.services.team import (
    EmployeeBranchesNotFound,
    EmployeeEmailAlreadyRegistered,
    create_employee,
)


router = APIRouter(tags=["Team"])


@router.post(
    "/employees",
    response_model=EmployeeCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_employee_endpoint(
    employee_data: EmployeeCreateRequest,
    membership: CompanyMembership = Depends(
        require_roles("OWNER")
    ),
    db: Session = Depends(get_db),
):
    try:
        return create_employee(
            db=db,
            actor=membership,
            employee_data=employee_data,
        )

    except EmployeeEmailAlreadyRegistered:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )

    except EmployeeBranchesNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="One or more branches were not found or are inactive.",
        )

    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Unable to create employee due to a data conflict.",
        )

    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to create employee.",
        )
