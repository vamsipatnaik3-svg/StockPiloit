from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.core.branch_scope import resolve_branch_scope
from app.core.security import hash_password
from app.models import (AnalystAnalyticsGrant, AnalystAnalyticsGrantBranch,
    Branch, BranchMembership, CompanyMembership, User)


PASSWORD = "Grant_Test_Password_123!"


def owner_setup(client, sessions, suffix=None):
    suffix = suffix or uuid4().hex[:10]
    email = f"grant-owner-{suffix}@example.com"
    response = client.post("/api/v1/auth/register", json={
        "full_name": "Grant Owner", "email": email, "password": PASSWORD,
        "company_name": f"Grant Company {suffix}", "industry": "grocery",
        "country_code": "IN", "currency": "INR", "timezone": "Asia/Kolkata",
    })
    assert response.status_code == 201, response.text
    login = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    token = login.cookies.get("stockpilot_session")
    with sessions() as db:
        owner = db.scalar(select(CompanyMembership).join(User).where(User.email == email))
        company_id = owner.company_id
    branches = []
    for index in (1, 2):
        result = client.post("/api/v1/branches", cookies={"stockpilot_session": token}, json={
            "name": f"Branch {index}", "code": f"G{index}-{suffix[:5]}",
            "country_code": "IN", "timezone": "Asia/Kolkata",
        })
        assert result.status_code == 201, result.text
        branches.append(result.json()["id"])
    return token, company_id, branches


def add_member(sessions, company_id, role, email, branch_ids=()):
    with sessions() as db:
        user = User(full_name=role.title(), email=email,
            password_hash=hash_password(PASSWORD), is_active=True)
        db.add(user)
        db.flush()
        member = CompanyMembership(company_id=company_id, user_id=user.id, role=role)
        db.add(member)
        db.flush()
        for branch_id in branch_ids:
            db.add(BranchMembership(branch_id=UUID(str(branch_id)),
                company_membership_id=member.id))
        db.commit()
        return member.id


def login(client, email):
    response = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return response.cookies.get("stockpilot_session")


def test_owner_creates_company_and_selected_branch_grants_and_lists_history(test_environment):
    client, sessions = test_environment
    owner_token, company_id, branches = owner_setup(client, sessions)
    analyst_id = add_member(sessions, company_id, "ANALYST", "grant-analyst@example.com", branches)
    cookies = {"stockpilot_session": owner_token}

    company = client.post("/api/v1/analyst-analytics-grants", cookies=cookies, json={
        "analyst_membership_id": str(analyst_id), "scope_type": "COMPANY",
    })
    assert company.status_code == 201, company.text
    assert company.json()["scope_type"] == "COMPANY"
    assert company.json()["branch_ids"] == []

    assert client.post(f"/api/v1/analyst-analytics-grants/{company.json()['id']}/revoke",
        cookies=cookies).status_code == 200
    selected = client.post("/api/v1/analyst-analytics-grants", cookies=cookies, json={
        "analyst_membership_id": str(analyst_id), "scope_type": "BRANCHES",
        "branch_ids": [branches[0]],
    })
    assert selected.status_code == 201, selected.text
    assert selected.json()["branch_ids"] == [branches[0]]

    listing = client.get("/api/v1/analyst-analytics-grants", cookies=cookies)
    assert listing.status_code == 200
    assert listing.json()["total"] == 2
    by_id = {item["id"]: item for item in listing.json()["items"]}
    assert by_id[company.json()["id"]]["revoked_at"] is not None
    assert by_id[selected.json()["id"]]["revoked_at"] is None


@pytest.mark.parametrize("role", ["MANAGER", "ANALYST", "STAFF"])
def test_only_owner_can_administer_grants(test_environment, role):
    client, sessions = test_environment
    owner_token, company_id, branches = owner_setup(client, sessions)
    analyst_id = add_member(sessions, company_id, "ANALYST", f"target-{role}@example.com", branches)
    actor_email = f"actor-{role.lower()}@example.com"
    add_member(sessions, company_id, role, actor_email, branches)
    token = login(client, actor_email)
    denied = client.post("/api/v1/analyst-analytics-grants",
        cookies={"stockpilot_session": token}, json={
            "analyst_membership_id": str(analyst_id), "scope_type": "COMPANY",
        })
    assert denied.status_code == 403
    # Even if the caller knows an active grant identifier, revoke is owner-only.
    created = client.post("/api/v1/analyst-analytics-grants",
        cookies={"stockpilot_session": owner_token}, json={
            "analyst_membership_id": str(analyst_id), "scope_type": "COMPANY",
        })
    assert created.status_code == 201
    denied_revoke = client.post(
        f"/api/v1/analyst-analytics-grants/{created.json()['id']}/revoke",
        cookies={"stockpilot_session": token})
    assert denied_revoke.status_code == 403


def test_cross_company_target_branch_invalid_shape_and_duplicate_active_grant_rejected(test_environment):
    client, sessions = test_environment
    owner_token, company_id, branches = owner_setup(client, sessions)
    target_id = add_member(sessions, company_id, "ANALYST", "grant-target@example.com")
    non_analyst_id = add_member(sessions, company_id, "MANAGER", "grant-non-analyst@example.com", branches)
    other_owner_token, other_company_id, other_branches = owner_setup(client, sessions, "other-company")
    other_target = add_member(sessions, other_company_id, "ANALYST", "foreign-grant-target@example.com")
    cookies = {"stockpilot_session": owner_token}
    url = "/api/v1/analyst-analytics-grants"

    for body in [
        {"analyst_membership_id": str(other_target), "scope_type": "COMPANY"},
        {"analyst_membership_id": str(non_analyst_id), "scope_type": "COMPANY"},
        {"analyst_membership_id": str(target_id), "scope_type": "BRANCHES", "branch_ids": []},
        {"analyst_membership_id": str(target_id), "scope_type": "COMPANY", "branch_ids": [branches[0]]},
        {"analyst_membership_id": str(target_id), "scope_type": "BRANCHES", "branch_ids": [branches[0], branches[0]]},
        {"analyst_membership_id": str(target_id), "scope_type": "BRANCHES", "branch_ids": [other_branches[0]]},
        {"analyst_membership_id": str(uuid4()), "scope_type": "COMPANY"},
    ]:
        response = client.post(url, cookies=cookies, json=body)
        assert response.status_code in {404, 409, 422}, (body, response.text)

    body = {"analyst_membership_id": str(target_id), "scope_type": "BRANCHES",
        "branch_ids": [branches[0]]}
    assert client.post(url, cookies=cookies, json=body).status_code == 201
    duplicate = client.post(url, cookies=cookies, json=body)
    assert duplicate.status_code == 409


def test_revoked_grant_no_longer_resolves_analyst_scope(test_environment):
    client, sessions = test_environment
    owner_token, company_id, branches = owner_setup(client, sessions)
    analyst_id = add_member(sessions, company_id, "ANALYST", "scope-analyst@example.com", branches)
    grant = client.post("/api/v1/analyst-analytics-grants",
        cookies={"stockpilot_session": owner_token}, json={
            "analyst_membership_id": str(analyst_id), "scope_type": "BRANCHES",
            "branch_ids": [branches[0]],
        }).json()
    with sessions() as db:
        analyst = db.get(CompanyMembership, UUID(str(analyst_id)))
        scope = resolve_branch_scope(db, analyst)
        assert scope.branch_ids == frozenset({UUID(branches[0])})
    response = client.post(f"/api/v1/analyst-analytics-grants/{grant['id']}/revoke",
        cookies={"stockpilot_session": owner_token})
    assert response.status_code == 200
    with sessions() as db:
        analyst = db.get(CompanyMembership, UUID(str(analyst_id)))
        with pytest.raises(HTTPException) as exc:
            resolve_branch_scope(db, analyst)
        assert exc.value.status_code == 403


def test_branch_scope_owner_manager_staff_and_analyst_filtering(test_environment):
    client, sessions = test_environment
    owner_token, company_id, branches = owner_setup(client, sessions)
    manager_id = add_member(sessions, company_id, "MANAGER", "scope-manager@example.com", [branches[0]])
    staff_id = add_member(sessions, company_id, "STAFF", "scope-staff@example.com", [branches[1]])
    analyst_id = add_member(sessions, company_id, "ANALYST", "scope-selected@example.com", [branches[0], branches[1]])
    grant = client.post("/api/v1/analyst-analytics-grants",
        cookies={"stockpilot_session": owner_token}, json={
            "analyst_membership_id": str(analyst_id), "scope_type": "BRANCHES",
            "branch_ids": [branches[1]],
        })
    assert grant.status_code == 201
    company_analyst_id = add_member(sessions, company_id, "ANALYST", "scope-company@example.com")
    assert client.post("/api/v1/analyst-analytics-grants",
        cookies={"stockpilot_session": owner_token}, json={
            "analyst_membership_id": str(company_analyst_id), "scope_type": "COMPANY",
        }).status_code == 201

    with sessions() as db:
        # Select the owner membership associated with this test company.
        owner = db.scalar(select(CompanyMembership).where(
            CompanyMembership.company_id == company_id, CompanyMembership.role == "OWNER"))
        manager = db.get(CompanyMembership, UUID(str(manager_id)))
        staff = db.get(CompanyMembership, UUID(str(staff_id)))
        analyst = db.get(CompanyMembership, UUID(str(analyst_id)))
        company_analyst = db.get(CompanyMembership, UUID(str(company_analyst_id)))
        owner_scope = resolve_branch_scope(db, owner)
        manager_scope = resolve_branch_scope(db, manager)
        staff_scope = resolve_branch_scope(db, staff)
        analyst_scope = resolve_branch_scope(db, analyst)
        company_scope = resolve_branch_scope(db, company_analyst)
        assert owner_scope.scope_type == "COMPANY"
        assert owner_scope.branch_ids == frozenset(UUID(item) for item in branches)
        assert manager_scope.branch_ids == frozenset({UUID(branches[0])})
        assert staff_scope.branch_ids == frozenset({UUID(branches[1])})
        assert analyst_scope.branch_ids == frozenset({UUID(branches[1])})
        assert company_scope.scope_type == "COMPANY"
        assert company_scope.branch_ids == frozenset(UUID(item) for item in branches)
        assert resolve_branch_scope(db, company_analyst,
            [UUID(item) for item in branches]).branch_ids == company_scope.branch_ids
        scoped_count = db.scalar(select(func.count(Branch.id)).where(
            *manager_scope.criteria(Branch.company_id, Branch.id)))
        assert scoped_count == 1
        with pytest.raises(HTTPException) as exc:
            resolve_branch_scope(db, manager, [UUID(branches[0]), UUID(branches[1])])
        assert exc.value.status_code == 404
        with pytest.raises(HTTPException) as exc:
            resolve_branch_scope(db, analyst, [UUID(branches[0])])
        assert exc.value.status_code == 404
        with pytest.raises(HTTPException) as exc:
            resolve_branch_scope(db, manager, [])
        assert exc.value.status_code == 422
        with pytest.raises(HTTPException) as exc:
            resolve_branch_scope(db, manager, [UUID(branches[0]), UUID(branches[0])])
        assert exc.value.status_code == 422


def test_manager_and_analyst_scopes_exclude_deactivated_branches(test_environment):
    client, sessions = test_environment
    owner_token, company_id, branches = owner_setup(client, sessions)
    manager_id = add_member(sessions, company_id, "MANAGER",
        "inactive-scope-manager@example.com", [branches[0]])
    selected_analyst_id = add_member(sessions, company_id, "ANALYST",
        "inactive-scope-selected@example.com")
    company_analyst_id = add_member(sessions, company_id, "ANALYST",
        "inactive-scope-company@example.com")
    owner_cookies = {"stockpilot_session": owner_token}
    selected = client.post("/api/v1/analyst-analytics-grants", cookies=owner_cookies,
        json={"analyst_membership_id": str(selected_analyst_id),
            "scope_type": "BRANCHES", "branch_ids": [branches[0]]})
    assert selected.status_code == 201, selected.text
    company = client.post("/api/v1/analyst-analytics-grants", cookies=owner_cookies,
        json={"analyst_membership_id": str(company_analyst_id), "scope_type": "COMPANY"})
    assert company.status_code == 201, company.text
    with sessions() as db:
        branch = db.get(Branch, UUID(branches[0]))
        branch.is_active = False
        db.commit()
        manager = db.get(CompanyMembership, UUID(str(manager_id)))
        selected_analyst = db.get(CompanyMembership, UUID(str(selected_analyst_id)))
        company_analyst = db.get(CompanyMembership, UUID(str(company_analyst_id)))
        for membership in (manager, selected_analyst):
            with pytest.raises(HTTPException) as exc:
                resolve_branch_scope(db, membership)
            assert exc.value.status_code == 403
        company_scope = resolve_branch_scope(db, company_analyst)
        assert company_scope.branch_ids == frozenset({UUID(branches[1])})
