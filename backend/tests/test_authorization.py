
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.dependencies import (
    get_current_membership,
    require_roles,
)
from app.models import Company, CompanyMembership, User


def create_test_user(db):
    user = User(
        full_name="Test User",
        email=f"{uuid4()}@example.com",
        password_hash="test-password-hash",
        is_active=True,
    )

    db.add(user)
    db.flush()

    return user


def create_test_company(db, user, role="OWNER"):
    company = Company(
        name=f"Test Company {uuid4().hex[:8]}",
        industry="grocery",
        country_code="IN",
        currency="INR",
        timezone="Asia/Kolkata",
    )

    db.add(company)
    db.flush()

    membership = CompanyMembership(
        company_id=company.id,
        user_id=user.id,
        role=role,
    )

    db.add(membership)
    db.flush()

    return company, membership


# --------------------------------------------------
# ROLE VALIDATION TESTS
# --------------------------------------------------

@pytest.mark.parametrize(
    "role",
    ["OWNER", "MANAGER", "STAFF", "ANALYST"],
)
def test_all_four_roles_are_supported(role):
    checker = require_roles(role)

    membership = CompanyMembership(
        company_id=uuid4(),
        user_id=uuid4(),
        role=role,
    )

    result = checker(membership=membership)

    assert result is membership


def test_staff_cannot_access_owner_only_endpoint():
    checker = require_roles("OWNER")

    membership = CompanyMembership(
        company_id=uuid4(),
        user_id=uuid4(),
        role="STAFF",
    )

    with pytest.raises(HTTPException) as exc:
        checker(membership=membership)

    assert exc.value.status_code == 403


def test_analyst_cannot_access_operational_endpoint():
    checker = require_roles("OWNER", "MANAGER", "STAFF")

    membership = CompanyMembership(
        company_id=uuid4(),
        user_id=uuid4(),
        role="ANALYST",
    )

    with pytest.raises(HTTPException) as exc:
        checker(membership=membership)

    assert exc.value.status_code == 403


def test_invalid_role_is_rejected():
    with pytest.raises(ValueError):
        require_roles("SUPER_ADMIN")


# --------------------------------------------------
# COMPANY MEMBERSHIP TESTS
# --------------------------------------------------

def test_user_can_access_own_company(test_environment):
    _, session_factory = test_environment

    with session_factory() as db:
        user = create_test_user(db)
        company, membership = create_test_company(db, user)

        db.commit()

        result = get_current_membership(
            user=user,
            db=db,
            company_id=None,
        )

        assert result.id == membership.id
        assert result.company_id == company.id
        assert result.role == "OWNER"


def test_user_can_select_company_using_company_id(test_environment):
    _, session_factory = test_environment

    with session_factory() as db:
        user = create_test_user(db)

        company_one, _ = create_test_company(db, user, "OWNER")
        company_two, membership_two = create_test_company(
            db,
            user,
            "ANALYST",
        )

        db.commit()

        result = get_current_membership(
            user=user,
            db=db,
            company_id=company_two.id,
        )

        assert result.id == membership_two.id
        assert result.company_id == company_two.id
        assert result.company_id != company_one.id


def test_multiple_companies_require_explicit_selection(test_environment):
    _, session_factory = test_environment

    with session_factory() as db:
        user = create_test_user(db)

        create_test_company(db, user, "OWNER")
        create_test_company(db, user, "MANAGER")

        db.commit()

        with pytest.raises(HTTPException) as exc:
            get_current_membership(
                user=user,
                db=db,
                company_id=None,
            )

        assert exc.value.status_code == 409


def test_user_cannot_access_another_company(test_environment):
    _, session_factory = test_environment

    with session_factory() as db:
        user = create_test_user(db)

        create_test_company(db, user, "OWNER")

        another_user = create_test_user(db)
        another_company, _ = create_test_company(
            db,
            another_user,
            "OWNER",
        )

        db.commit()

        with pytest.raises(HTTPException) as exc:
            get_current_membership(
                user=user,
                db=db,
                company_id=another_company.id,
            )

        assert exc.value.status_code == 403


def test_user_without_company_membership_is_rejected(test_environment):
    _, session_factory = test_environment

    with session_factory() as db:
        user = create_test_user(db)
        db.commit()

        with pytest.raises(HTTPException) as exc:
            get_current_membership(
                user=user,
                db=db,
                company_id=None,
            )

        assert exc.value.status_code == 403
