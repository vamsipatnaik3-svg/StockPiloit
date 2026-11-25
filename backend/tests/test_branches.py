
from uuid import UUID
from sqlalchemy.exc import IntegrityError
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

import pytest
from sqlalchemy import select

from app.models import (
    Branch,
    BranchMembership,
    CompanyMembership,
    User,
)


def register_and_login(client, email, company_name):
    registration_response = client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Branch Test Owner",
            "email": email,
            "password": "StockPilot_Test_123!",
            "company_name": company_name,
            "industry": "grocery",
            "country_code": "IN",
            "currency": "INR",
            "timezone": "Asia/Kolkata",
        },
    )

    assert registration_response.status_code == 201

    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "email": email,
            "password": "StockPilot_Test_123!",
        },
    )

    assert login_response.status_code == 200

    token = login_response.cookies.get("stockpilot_session")
    assert token is not None

    return registration_response.json(), token


def branch_payload(name="Hyderabad Main Branch", code="HYD01"):
    return {
        "name": name,
        "code": code,
        "address_line1": "Main Road",
        "address_line2": None,
        "city": "Hyderabad",
        "state": "Telangana",
        "postal_code": "500001",
        "country_code": "IN",
        "timezone": "Asia/Kolkata",
    }


def get_company_owner_membership(session_factory, company_id):
    with session_factory() as db:
        membership = db.scalar(
            select(CompanyMembership).where(
                CompanyMembership.company_id == UUID(company_id)
            )
        )

        assert membership is not None
        return membership.id


def create_company_member(
    session_factory,
    company_id,
    email,
    role="STAFF",
):
    with session_factory() as db:
        user = User(
            full_name="Branch Test Member",
            email=email,
            password_hash="test-password-hash",
            is_active=True,
        )

        db.add(user)
        db.flush()

        membership = CompanyMembership(
            company_id=UUID(company_id),
            user_id=user.id,
            role=role,
        )

        db.add(membership)
        db.commit()
        db.refresh(membership)

        return membership.id


def change_membership_role(session_factory, membership_id, role):
    with session_factory() as db:
        membership = db.get(CompanyMembership, membership_id)

        assert membership is not None

        membership.role = role
        db.commit()


def create_branch(client, token, name="Hyderabad Branch", code="HYD01"):
    response = client.post(
        "/api/v1/branches",
        json=branch_payload(name, code),
        cookies={"stockpilot_session": token},
    )

    assert response.status_code == 201
    return response.json()


def assign_member(client, token, branch_id, membership_id):
    return client.post(
        f"/api/v1/branches/{branch_id}/members",
        json={"company_membership_id": str(membership_id)},
        cookies={"stockpilot_session": token},
    )


def test_owner_can_create_branch(test_environment):
    client, session_factory = test_environment

    _, token = register_and_login(
        client,
        "branch.owner@example.com",
        "Branch Test Company",
    )

    response = client.post(
        "/api/v1/branches",
        json=branch_payload(),
        cookies={"stockpilot_session": token},
    )

    assert response.status_code == 201

    data = response.json()

    assert data["name"] == "Hyderabad Main Branch"
    assert data["code"] == "HYD01"
    assert data["city"] == "Hyderabad"
    assert data["country_code"] == "IN"
    assert data["is_active"] is True

    with session_factory() as db:
        branch = db.scalar(select(Branch))

        assert branch is not None
        assert branch.name == "Hyderabad Main Branch"


def test_manager_cannot_create_branch(test_environment):
    client, session_factory = test_environment

    registration, token = register_and_login(
        client,
        "branch.manager@example.com",
        "Manager Test Company",
    )

    membership_id = get_company_owner_membership(
        session_factory,
        registration["company_id"],
    )

    change_membership_role(
        session_factory,
        membership_id,
        "MANAGER",
    )

    response = client.post(
        "/api/v1/branches",
        json=branch_payload(),
        cookies={"stockpilot_session": token},
    )

    assert response.status_code == 403


def test_owner_can_list_company_branches(test_environment):
    client, _ = test_environment

    _, token = register_and_login(
        client,
        "branch.list@example.com",
        "Branch List Company",
    )

    create_branch(client, token, "Hyderabad Branch", "HYD01")
    create_branch(client, token, "Bangalore Branch", "BLR01")

    response = client.get(
        "/api/v1/branches",
        cookies={"stockpilot_session": token},
    )

    assert response.status_code == 200

    branches = response.json()

    assert len(branches) == 2
    assert {branch["name"] for branch in branches} == {
        "Hyderabad Branch",
        "Bangalore Branch",
    }


def test_owner_cannot_see_another_company_branches(test_environment):
    client, _ = test_environment

    _, first_token = register_and_login(
        client,
        "company.one@example.com",
        "Company One",
    )

    _, second_token = register_and_login(
        client,
        "company.two@example.com",
        "Company Two",
    )

    create_branch(
        client,
        first_token,
        "Company One Branch",
        "ONE01",
    )

    create_branch(
        client,
        second_token,
        "Company Two Branch",
        "TWO01",
    )

    response = client.get(
        "/api/v1/branches",
        cookies={"stockpilot_session": first_token},
    )

    assert response.status_code == 200

    branches = response.json()

    assert len(branches) == 1
    assert branches[0]["name"] == "Company One Branch"


def test_duplicate_branch_name_is_rejected(test_environment):
    client, _ = test_environment

    _, token = register_and_login(
        client,
        "branch.duplicate@example.com",
        "Duplicate Test Company",
    )

    first_response = client.post(
        "/api/v1/branches",
        json=branch_payload("Hyderabad Branch", "HYD01"),
        cookies={"stockpilot_session": token},
    )

    duplicate_response = client.post(
        "/api/v1/branches",
        json=branch_payload("Hyderabad Branch", "HYD02"),
        cookies={"stockpilot_session": token},
    )

    assert first_response.status_code == 201
    assert duplicate_response.status_code == 409


def test_owner_can_assign_and_list_branch_members(test_environment):
    client, session_factory = test_environment

    registration, token = register_and_login(
        client,
        "assign.owner@example.com",
        "Assignment Company",
    )

    branch = create_branch(client, token)

    member_id = create_company_member(
        session_factory,
        registration["company_id"],
        "assigned.member@example.com",
    )

    response = assign_member(
        client,
        token,
        branch["id"],
        member_id,
    )

    assert response.status_code == 201

    data = response.json()

    assert data["branch_id"] == branch["id"]
    assert data["company_membership_id"] == str(member_id)
    assert data["email"] == "assigned.member@example.com"
    assert data["role"] == "STAFF"

    list_response = client.get(
        f"/api/v1/branches/{branch['id']}/members",
        cookies={"stockpilot_session": token},
    )

    assert list_response.status_code == 200

    members = list_response.json()

    assert len(members) == 1
    assert members[0]["company_membership_id"] == str(member_id)


def test_owner_can_remove_branch_member(test_environment):
    client, session_factory = test_environment

    registration, token = register_and_login(
        client,
        "remove.owner@example.com",
        "Removal Company",
    )

    branch = create_branch(client, token)

    member_id = create_company_member(
        session_factory,
        registration["company_id"],
        "remove.member@example.com",
    )

    assignment_response = assign_member(
        client,
        token,
        branch["id"],
        member_id,
    )

    assert assignment_response.status_code == 201

    delete_response = client.delete(
        f"/api/v1/branches/{branch['id']}/members/{member_id}",
        cookies={"stockpilot_session": token},
    )

    assert delete_response.status_code == 204

    list_response = client.get(
        f"/api/v1/branches/{branch['id']}/members",
        cookies={"stockpilot_session": token},
    )

    assert list_response.status_code == 200
    assert list_response.json() == []


def test_duplicate_branch_member_assignment_is_rejected(test_environment):
    client, session_factory = test_environment

    registration, token = register_and_login(
        client,
        "duplicate.assignment@example.com",
        "Duplicate Assignment Company",
    )

    branch = create_branch(client, token)

    member_id = create_company_member(
        session_factory,
        registration["company_id"],
        "duplicate.member@example.com",
    )

    first_response = assign_member(
        client,
        token,
        branch["id"],
        member_id,
    )

    second_response = assign_member(
        client,
        token,
        branch["id"],
        member_id,
    )

    assert first_response.status_code == 201
    assert second_response.status_code == 409


def test_member_from_another_company_cannot_be_assigned(test_environment):
    client, session_factory = test_environment

    first_registration, first_token = register_and_login(
        client,
        "cross.company.one@example.com",
        "Cross Company One",
    )

    second_registration, _ = register_and_login(
        client,
        "cross.company.two@example.com",
        "Cross Company Two",
    )

    branch = create_branch(
        client,
        first_token,
        "Company One Branch",
        "ONE01",
    )

    other_company_membership_id = get_company_owner_membership(
        session_factory,
        second_registration["company_id"],
    )

    response = assign_member(
        client,
        first_token,
        branch["id"],
        other_company_membership_id,
    )

    assert response.status_code == 404


def test_manager_can_view_members_of_assigned_branch(test_environment):
    client, session_factory = test_environment

    registration, token = register_and_login(
        client,
        "manager.view@example.com",
        "Manager View Company",
    )

    branch = create_branch(client, token)

    manager_membership_id = get_company_owner_membership(
        session_factory,
        registration["company_id"],
    )

    employee_membership_id = create_company_member(
        session_factory,
        registration["company_id"],
        "manager.employee@example.com",
    )

    employee_assignment = assign_member(
        client,
        token,
        branch["id"],
        employee_membership_id,
    )

    assert employee_assignment.status_code == 201

    with session_factory() as db:
        db.add(
            BranchMembership(
                branch_id=UUID(branch["id"]),
                company_membership_id=manager_membership_id,
            )
        )
        db.commit()

    change_membership_role(
        session_factory,
        manager_membership_id,
        "MANAGER",
    )

    response = client.get(
        f"/api/v1/branches/{branch['id']}/members",
        cookies={"stockpilot_session": token},
    )

    assert response.status_code == 200

    members = response.json()

    assert len(members) == 2
    assert {
        member["company_membership_id"]
        for member in members
    } == {
        str(manager_membership_id),
        str(employee_membership_id),
    }


def test_manager_cannot_view_unassigned_branch(test_environment):
    client, session_factory = test_environment

    registration, token = register_and_login(
        client,
        "manager.restricted@example.com",
        "Manager Restricted Company",
    )

    assigned_branch = create_branch(
        client,
        token,
        "Assigned Branch",
        "ASG01",
    )

    unassigned_branch = create_branch(
        client,
        token,
        "Unassigned Branch",
        "UNAS01",
    )

    manager_membership_id = get_company_owner_membership(
        session_factory,
        registration["company_id"],
    )

    with session_factory() as db:
        db.add(
            BranchMembership(
                branch_id=UUID(assigned_branch["id"]),
                company_membership_id=manager_membership_id,
            )
        )
        db.commit()

    change_membership_role(
        session_factory,
        manager_membership_id,
        "MANAGER",
    )

    response = client.get(
        f"/api/v1/branches/{unassigned_branch['id']}/members",
        cookies={"stockpilot_session": token},
    )

    assert response.status_code == 403


def test_manager_cannot_assign_or_remove_branch_members(test_environment):
    client, session_factory = test_environment

    registration, token = register_and_login(
        client,
        "manager.permissions@example.com",
        "Manager Permissions Company",
    )

    branch = create_branch(client, token)

    manager_membership_id = get_company_owner_membership(
        session_factory,
        registration["company_id"],
    )

    employee_membership_id = create_company_member(
        session_factory,
        registration["company_id"],
        "manager.permissions.employee@example.com",
    )

    assignment = assign_member(
        client,
        token,
        branch["id"],
        employee_membership_id,
    )

    assert assignment.status_code == 201

    change_membership_role(
        session_factory,
        manager_membership_id,
        "MANAGER",
    )

    assign_response = assign_member(
        client,
        token,
        branch["id"],
        manager_membership_id,
    )

    delete_response = client.delete(
        f"/api/v1/branches/{branch['id']}/members/{employee_membership_id}",
        cookies={"stockpilot_session": token},
    )

    assert assign_response.status_code == 403
    assert delete_response.status_code == 403


@pytest.mark.parametrize("role", ["STAFF", "ANALYST"])
def test_staff_and_analyst_cannot_manage_branch_members(
    test_environment,
    role,
):
    client, session_factory = test_environment

    registration, token = register_and_login(
        client,
        f"{role.lower()}.permissions@example.com",
        f"{role} Permissions Company",
    )

    branch = create_branch(client, token)

    actor_membership_id = get_company_owner_membership(
        session_factory,
        registration["company_id"],
    )

    employee_membership_id = create_company_member(
        session_factory,
        registration["company_id"],
        f"{role.lower()}.employee@example.com",
    )

    assignment = assign_member(
        client,
        token,
        branch["id"],
        employee_membership_id,
    )

    assert assignment.status_code == 201

    change_membership_role(
        session_factory,
        actor_membership_id,
        role,
    )

    assign_response = assign_member(
        client,
        token,
        branch["id"],
        actor_membership_id,
    )

    delete_response = client.delete(
        f"/api/v1/branches/{branch['id']}/members/{employee_membership_id}",
        cookies={"stockpilot_session": token},
    )

    assert assign_response.status_code == 403
    assert delete_response.status_code == 403

@pytest.mark.parametrize("role", ["MANAGER", "STAFF", "ANALYST"])
def test_non_owner_can_list_only_assigned_branches(
    test_environment,
    role,
):
    client, session_factory = test_environment

    registration, token = register_and_login(
        client,
        f"{role.lower()}.branch.list@example.com",
        f"{role} Branch Listing Company",
    )

    assigned_branch = create_branch(
        client,
        token,
        "Assigned Branch",
        "ASG01",
    )

    unassigned_branch = create_branch(
        client,
        token,
        "Unassigned Branch",
        "UNAS01",
    )

    membership_id = get_company_owner_membership(
        session_factory,
        registration["company_id"],
    )

    with session_factory() as db:
        db.add(
            BranchMembership(
                branch_id=UUID(assigned_branch["id"]),
                company_membership_id=membership_id,
            )
        )
        db.commit()

    change_membership_role(
        session_factory,
        membership_id,
        role,
    )

    response = client.get(
        "/api/v1/branches",
        cookies={"stockpilot_session": token},
    )

    assert response.status_code == 200

    branches = response.json()

    assert len(branches) == 1
    assert branches[0]["id"] == assigned_branch["id"]
    assert branches[0]["name"] == "Assigned Branch"


@pytest.mark.parametrize("role", ["MANAGER", "STAFF", "ANALYST"])
def test_non_owner_cannot_list_inactive_assigned_branch(
    test_environment,
    role,
):
    client, session_factory = test_environment

    registration, token = register_and_login(
        client,
        f"{role.lower()}.inactive@example.com",
        f"{role} Inactive Branch Company",
    )

    branch = create_branch(
        client,
        token,
        "Inactive Branch",
        "INACT01",
    )

    membership_id = get_company_owner_membership(
        session_factory,
        registration["company_id"],
    )

    with session_factory() as db:
        branch_record = db.get(Branch, UUID(branch["id"]))
        assert branch_record is not None
        branch_record.is_active = False

        db.add(
            BranchMembership(
                branch_id=UUID(branch["id"]),
                company_membership_id=membership_id,
            )
        )
        db.commit()

    change_membership_role(
        session_factory,
        membership_id,
        role,
    )

    response = client.get(
        "/api/v1/branches",
        cookies={"stockpilot_session": token},
    )

    assert response.status_code == 200
    assert response.json() == []


def test_owner_can_list_inactive_branches(test_environment):
    client, session_factory = test_environment

    registration, token = register_and_login(
        client,
        "owner.inactive@example.com",
        "Owner Inactive Branch Company",
    )

    branch = create_branch(
        client,
        token,
        "Inactive Branch",
        "INACT02",
    )

    with session_factory() as db:
        branch_record = db.get(Branch, UUID(branch["id"]))
        assert branch_record is not None
        branch_record.is_active = False
        db.commit()

    response = client.get(
        "/api/v1/branches",
        cookies={"stockpilot_session": token},
    )

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["is_active"] is False


@pytest.mark.parametrize("role", ["MANAGER", "STAFF", "ANALYST"])
def test_non_owner_cannot_access_inactive_branch_members(
    test_environment,
    role,
):
    client, session_factory = test_environment

    registration, token = register_and_login(
        client,
        f"{role.lower()}.inactive.access@example.com",
        f"{role} Inactive Access Company",
    )

    branch = create_branch(
        client,
        token,
        "Inactive Assigned Branch",
        "INACT03",
    )

    membership_id = get_company_owner_membership(
        session_factory,
        registration["company_id"],
    )

    with session_factory() as db:
        branch_record = db.get(Branch, UUID(branch["id"]))
        assert branch_record is not None

        branch_record.is_active = False

        db.add(
            BranchMembership(
                branch_id=UUID(branch["id"]),
                company_membership_id=membership_id,
            )
        )

        db.commit()

    change_membership_role(
        session_factory,
        membership_id,
        role,
    )

    response = client.get(
        f"/api/v1/branches/{branch['id']}/members",
        cookies={"stockpilot_session": token},
    )

    assert response.status_code == 404

def test_database_prevents_duplicate_branch_assignments(
    test_environment,
):
    client, session_factory = test_environment

    registration, token = register_and_login(
        client,
        "database.constraint@example.com",
        "Database Constraint Company",
    )

    branch = create_branch(client, token)

    member_id = create_company_member(
        session_factory,
        registration["company_id"],
        "database.constraint.member@example.com",
    )

    first_response = assign_member(
        client,
        token,
        branch["id"],
        member_id,
    )

    assert first_response.status_code == 201

    with session_factory() as db:
        duplicate = BranchMembership(
            branch_id=UUID(branch["id"]),
            company_membership_id=member_id,
        )

        db.add(duplicate)

        with pytest.raises(IntegrityError):
            db.commit()

        db.rollback()

    with session_factory() as db:
        assignments = db.scalars(
            select(BranchMembership).where(
                BranchMembership.branch_id == UUID(branch["id"]),
                BranchMembership.company_membership_id == member_id,
            )
        ).all()

        assert len(assignments) == 1

def test_owner_can_list_only_active_members_of_own_company(
    test_environment,
):
    client, session_factory = test_environment

    registration, token = register_and_login(
        client,
        "eligible.owner@example.com",
        "Eligible Members Company",
    )

    active_member_id = create_company_member(
        session_factory,
        registration["company_id"],
        "eligible.active@example.com",
    )

    with session_factory() as db:
        inactive_user = User(
            full_name="Inactive Employee",
            email="eligible.inactive@example.com",
            password_hash="test-password-hash",
            is_active=False,
        )
        db.add(inactive_user)
        db.flush()

        inactive_membership = CompanyMembership(
            company_id=UUID(registration["company_id"]),
            user_id=inactive_user.id,
            role="STAFF",
        )
        db.add(inactive_membership)
        db.commit()

    other_registration, _ = register_and_login(
        client,
        "eligible.other@example.com",
        "Another Company",
    )

    other_company_member_id = get_company_owner_membership(
        session_factory,
        other_registration["company_id"],
    )

    response = client.get(
        "/api/v1/branches/members/eligible",
        cookies={"stockpilot_session": token},
    )

    assert response.status_code == 200

    members = response.json()

    membership_ids = {
        member["membership_id"]
        for member in members
    }

    owner_membership_id = str(
        get_company_owner_membership(
            session_factory,
            registration["company_id"],
        )
    )

    assert membership_ids == {
        owner_membership_id,
        str(active_member_id),
    }

    assert str(other_company_member_id) not in membership_ids
    assert all(
        "password_hash" not in member
        for member in members
    )


def test_non_owner_cannot_list_eligible_company_members(
    test_environment,
):
    client, session_factory = test_environment

    registration, token = register_and_login(
        client,
        "eligible.manager@example.com",
        "Eligible Manager Company",
    )

    owner_membership_id = get_company_owner_membership(
        session_factory,
        registration["company_id"],
    )

    change_membership_role(
        session_factory,
        owner_membership_id,
        "MANAGER",
    )

    response = client.get(
        "/api/v1/branches/members/eligible",
        cookies={"stockpilot_session": token},
    )

    assert response.status_code == 403