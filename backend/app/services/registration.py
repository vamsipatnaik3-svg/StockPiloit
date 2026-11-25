from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models import Company, CompanyMembership, User
from app.schemas.auth import RegistrationRequest


class EmailAlreadyRegistered(Exception):
    pass


def register_company_owner(
    db: Session,
    registration: RegistrationRequest,
) -> tuple[User, Company]:

    try:
        with db.begin():

            # Check whether the email already exists.
            existing_user = db.scalar(
                select(User).where(
                    User.email == str(registration.email)
                )
            )

            if existing_user:
                raise EmailAlreadyRegistered(
                    "An account with this email already exists."
                )

            # Create company.
            company = Company(
                name=registration.company_name,
                industry=registration.industry,
                country_code=registration.country_code,
                currency=registration.currency,
                timezone=registration.timezone,
            )

            # Create user.
            user = User(
                full_name=registration.full_name,
                email=str(registration.email),
                password_hash=hash_password(registration.password),
                is_active=True,
            )

            db.add(company)
            db.add(user)
            db.flush()

            # Assign owner role.
            membership = CompanyMembership(
                company_id=company.id,
                user_id=user.id,
                role="OWNER",
            )

            db.add(membership)

        return user, company

    except IntegrityError:
        db.rollback()

        # Check whether a concurrent request registered this email.
        existing_user = db.scalar(
            select(User).where(
                User.email == str(registration.email)
            )
        )

        if existing_user:
            raise EmailAlreadyRegistered(
                "An account with this email already exists."
            )

        raise