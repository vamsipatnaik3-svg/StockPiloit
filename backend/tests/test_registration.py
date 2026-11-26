from sqlalchemy import select

from app.core.security import verify_password
from app.models import Company, CompanyMembership, User


def registration_payload():
    return {
        "full_name": "Test Owner",
        "email": "test.owner@example.com",
        "password": "StockPilot_Test_123!",
        "company_name": "Test Retail Store",
        "industry": "grocery",
        "country_code": "IN",
        "currency": "INR",
        "timezone": "Asia/Kolkata",
    }


def test_successful_company_registration(test_environment):
    client, session_factory = test_environment

    response = client.post(
        "/api/v1/auth/register",
        json=registration_payload(),
    )

    assert response.status_code == 201

    data = response.json()

    assert data["company_name"] == "Test Retail Store"
    assert data["user_email"] == "test.owner@example.com"
    assert data["role"] == "OWNER"

    with session_factory() as db:
        company = db.scalar(select(Company))
        user = db.scalar(select(User))
        membership = db.scalar(select(CompanyMembership))

        assert company is not None
        assert user is not None
        assert membership is not None

        assert company.name == "Test Retail Store"
        assert user.email == "test.owner@example.com"
        assert membership.role == "OWNER"

        assert verify_password(
            "StockPilot_Test_123!",
            user.password_hash,
        )

        assert user.password_hash != "StockPilot_Test_123!"


def test_duplicate_email_is_rejected(test_environment):
    client, session_factory = test_environment

    payload = registration_payload()

    first_response = client.post(
        "/api/v1/auth/register",
        json=payload,
    )

    second_response = client.post(
        "/api/v1/auth/register",
        json=payload,
    )

    assert first_response.status_code == 201
    assert second_response.status_code == 409

    with session_factory() as db:
        assert len(db.scalars(select(Company)).all()) == 1
        assert len(db.scalars(select(User)).all()) == 1
        assert len(db.scalars(select(CompanyMembership)).all()) == 1


def test_invalid_registration_is_rejected(test_environment):
    client, _ = test_environment

    payload = registration_payload()
    payload["email"] = "not-an-email"

    response = client.post(
        "/api/v1/auth/register",
        json=payload,
    )

    assert response.status_code == 422


def test_cafe_and_bakery_industries_are_supported_additively(test_environment):
    client, session_factory = test_environment
    for industry in ("CAFE", "BAKERY"):
        payload = registration_payload()
        payload["industry"] = industry
        payload["email"] = f"{industry.lower()}-owner@example.com"
        payload["company_name"] = f"{industry} Company"
        response = client.post("/api/v1/auth/register", json=payload)
        assert response.status_code == 201, response.text
    with session_factory() as db:
        assert {company.industry for company in db.scalars(select(Company)).all()} == {"CAFE", "BAKERY"}
