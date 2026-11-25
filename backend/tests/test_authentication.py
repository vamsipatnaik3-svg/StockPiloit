import hashlib
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models import User, UserSession


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


def register_test_user(client):
    response = client.post(
        "/api/v1/auth/register",
        json=registration_payload(),
    )

    assert response.status_code == 201
    return response.json()


def login_payload():
    return {
        "email": "test.owner@example.com",
        "password": "StockPilot_Test_123!",
    }


def login_test_user(client):
    register_test_user(client)

    response = client.post(
        "/api/v1/auth/login",
        json=login_payload(),
    )

    assert response.status_code == 200
    return response


# --------------------------------------------------
# LOGIN TESTS
# --------------------------------------------------

def test_successful_login_creates_session(test_environment):
    client, session_factory = test_environment

    response = login_test_user(client)

    data = response.json()

    assert data["email"] == "test.owner@example.com"
    assert data["full_name"] == "Test Owner"
    assert "user_id" in data

    cookie = response.cookies.get("stockpilot_session")

    assert cookie is not None

    cookie_details = response.headers.get("set-cookie", "").lower()

    assert "httponly" in cookie_details
    assert "samesite=lax" in cookie_details

    token_hash = hashlib.sha256(
        cookie.encode("utf-8")
    ).hexdigest()

    with session_factory() as db:
        user_session = db.scalar(
            select(UserSession).where(
                UserSession.token_hash == token_hash
            )
        )

        assert user_session is not None
        assert str(user_session.user_id) == data["user_id"]
        assert user_session.revoked_at is None
        assert user_session.expires_at is not None


def test_login_rejects_incorrect_password(test_environment):
    client, session_factory = test_environment

    register_test_user(client)

    payload = login_payload()
    payload["password"] = "WrongPassword_123!"

    response = client.post(
        "/api/v1/auth/login",
        json=payload,
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password."

    with session_factory() as db:
        assert db.scalar(select(UserSession)) is None


def test_login_rejects_unknown_email(test_environment):
    client, session_factory = test_environment

    payload = login_payload()
    payload["email"] = "unknown@example.com"

    response = client.post(
        "/api/v1/auth/login",
        json=payload,
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password."

    with session_factory() as db:
        assert db.scalar(select(UserSession)) is None


def test_login_rejects_inactive_user(test_environment):
    client, session_factory = test_environment

    register_test_user(client)

    with session_factory() as db:
        user = db.scalar(
            select(User).where(
                User.email == "test.owner@example.com"
            )
        )

        assert user is not None

        user.is_active = False
        db.commit()

    response = client.post(
        "/api/v1/auth/login",
        json=login_payload(),
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password."

    with session_factory() as db:
        assert db.scalar(select(UserSession)) is None


# --------------------------------------------------
# CURRENT USER / ME TESTS
# --------------------------------------------------

def test_me_rejects_unauthenticated_user(test_environment):
    client, _ = test_environment

    response = client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required."


def test_me_returns_authenticated_user(test_environment):
    client, _ = test_environment

    login_test_user(client)

    response = client.get("/api/v1/auth/me")

    assert response.status_code == 200

    data = response.json()

    assert data["email"] == "test.owner@example.com"
    assert data["full_name"] == "Test Owner"
    assert "user_id" in data


def test_me_rejects_revoked_session(test_environment):
    client, session_factory = test_environment

    login_response = login_test_user(client)

    raw_token = login_response.cookies.get("stockpilot_session")

    token_hash = hashlib.sha256(
        raw_token.encode("utf-8")
    ).hexdigest()

    with session_factory() as db:
        user_session = db.scalar(
            select(UserSession).where(
                UserSession.token_hash == token_hash
            )
        )

        assert user_session is not None

        user_session.revoked_at = datetime.now(timezone.utc)
        db.commit()

    response = client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or expired session."


def test_me_rejects_expired_session(test_environment):
    client, session_factory = test_environment

    login_response = login_test_user(client)

    raw_token = login_response.cookies.get("stockpilot_session")

    token_hash = hashlib.sha256(
        raw_token.encode("utf-8")
    ).hexdigest()

    with session_factory() as db:
        user_session = db.scalar(
            select(UserSession).where(
                UserSession.token_hash == token_hash
            )
        )

        assert user_session is not None

        user_session.expires_at = (
            datetime.now(timezone.utc) - timedelta(minutes=5)
        )

        db.commit()

    response = client.get("/api/v1/auth/me")

    assert response.status_code == 401

    with session_factory() as db:
        user_session = db.scalar(
            select(UserSession).where(
                UserSession.token_hash == token_hash
            )
        )

        assert user_session.revoked_at is not None


# --------------------------------------------------
# LOGOUT TESTS
# --------------------------------------------------

def test_successful_logout_revokes_session_and_clears_cookie(
    test_environment,
):
    client, session_factory = test_environment

    login_response = login_test_user(client)

    raw_token = login_response.cookies.get("stockpilot_session")
    assert raw_token is not None

    token_hash = hashlib.sha256(
        raw_token.encode("utf-8")
    ).hexdigest()

    response = client.post("/api/v1/auth/logout")

    assert response.status_code == 200
    assert response.json()["message"] == "Successfully logged out."

    cookie_details = response.headers.get("set-cookie", "").lower()

    assert "stockpilot_session" in cookie_details
    assert "max-age=0" in cookie_details

    with session_factory() as db:
        user_session = db.scalar(
            select(UserSession).where(
                UserSession.token_hash == token_hash
            )
        )

        assert user_session is not None
        assert user_session.revoked_at is not None


def test_logout_revoked_session_cannot_access_me(test_environment):
    client, _ = test_environment

    login_response = login_test_user(client)

    raw_token = login_response.cookies.get("stockpilot_session")
    assert raw_token is not None

    logout_response = client.post("/api/v1/auth/logout")

    assert logout_response.status_code == 200

    # Try using the old token again.
    response = client.get(
        "/api/v1/auth/me",
        cookies={"stockpilot_session": raw_token},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or expired session."


def test_logout_without_session_cookie(test_environment):
    client, _ = test_environment

    response = client.post("/api/v1/auth/logout")

    assert response.status_code == 200
    assert response.json()["message"] == "Successfully logged out."

    cookie_details = response.headers.get("set-cookie", "").lower()

    assert "stockpilot_session" in cookie_details
    assert "max-age=0" in cookie_details
