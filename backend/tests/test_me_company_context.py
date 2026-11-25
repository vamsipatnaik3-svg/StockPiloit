
from uuid import uuid4, UUID

from app.models import Company, CompanyMembership, User


def registration_payload():
    email = f"{uuid4()}@example.com"

    return {
        "full_name": "Tavuno Test Owner",
        "email": email,
        "password": "Tavuno_Test_123!",
        "company_name": "Tavuno Retail Store",
        "industry": "grocery",
        "country_code": "IN",
        "currency": "INR",
        "timezone": "Asia/Kolkata",
    }


def register_and_login(client):
    payload = registration_payload()

    registration_response = client.post(
        "/api/v1/auth/register",
        json=payload,
    )

    assert registration_response.status_code == 201

    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "email": payload["email"],
            "password": payload["password"],
        },
    )

    assert login_response.status_code == 200

    return registration_response.json()


def test_me_returns_company_and_role(test_environment):
    client, _ = test_environment

    registration = register_and_login(client)

    response = client.get("/api/v1/auth/me")

    assert response.status_code == 200

    data = response.json()

    assert data["user_id"] == registration["user_id"]
    assert data["company_id"] == registration["company_id"]
    assert data["company_name"] == "Tavuno Retail Store"
    assert data["role"] == "OWNER"


def test_me_rejects_unrelated_company(test_environment):
    client, _ = test_environment

    register_and_login(client)

    response = client.get(
        "/api/v1/auth/me",
        headers={
            "X-Company-ID": str(uuid4()),
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == (
        "You do not have access to this company."
    )


def test_me_requires_company_selection_for_multiple_memberships(
    test_environment,
):
    client, session_factory = test_environment

    registration = register_and_login(client)

    user_id = UUID(registration["user_id"])

    with session_factory() as db:
        second_company = Company(
            name="Second Retail Company",
            industry="fashion",
            country_code="IN",
            currency="INR",
            timezone="Asia/Kolkata",
        )

        db.add(second_company)
        db.flush()

        second_membership = CompanyMembership(
            company_id=second_company.id,
            user_id=user_id,
            role="ANALYST",
        )

        db.add(second_membership)
        db.commit()

        second_company_id = str(second_company.id)

    # Multiple memberships without selecting a company.
    response = client.get("/api/v1/auth/me")

    assert response.status_code == 409

    # Explicitly select the second company.
    response = client.get(
        "/api/v1/auth/me",
        headers={
            "X-Company-ID": second_company_id,
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["company_name"] == "Second Retail Company"
    assert data["company_id"] == second_company_id
    assert data["role"] == "ANALYST"
