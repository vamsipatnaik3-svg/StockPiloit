
import hashlib
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.security import verify_password
from app.models import PasswordResetToken, User, UserSession
from app.services.authentication import create_login_session
from app.services.password_reset import (
    create_password_reset_token,
    reset_password,
)
from app.schemas.auth import LoginRequest


def register_test_user(client):
    response = client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Test Owner",
            "email": "reset.owner@example.com",
            "password": "StockPilot_Test_123!",
            "company_name": "Reset Test Store",
            "industry": "grocery",
            "country_code": "IN",
            "currency": "INR",
            "timezone": "Asia/Kolkata",
        },
    )

    assert response.status_code == 201
    return response.json()


def get_test_user(db):
    return db.scalar(
        select(User).where(
            User.email == "reset.owner@example.com"
        )
    )


def test_password_reset_token_is_stored_as_hash(test_environment):
    client, session_factory = test_environment
    register_test_user(client)

    with session_factory() as db:
        user = get_test_user(db)
        raw_token = create_password_reset_token(db, user)

        expected_hash = hashlib.sha256(
            raw_token.encode("utf-8")
        ).hexdigest()

        stored_token = db.scalar(
            select(PasswordResetToken).where(
                PasswordResetToken.user_id == user.id
            )
        )

        assert stored_token is not None
        assert stored_token.token_hash == expected_hash
        assert stored_token.token_hash != raw_token
        assert stored_token.used_at is None
        assert stored_token.expires_at is not None


def test_new_reset_token_invalidates_previous_token(test_environment):
    client, session_factory = test_environment
    register_test_user(client)

    with session_factory() as db:
        user = get_test_user(db)

        first_token = create_password_reset_token(db, user)
        second_token = create_password_reset_token(db, user)

        assert first_token != second_token

        first_hash = hashlib.sha256(
            first_token.encode("utf-8")
        ).hexdigest()

        first_record = db.scalar(
            select(PasswordResetToken).where(
                PasswordResetToken.token_hash == first_hash
            )
        )

        assert first_record is not None
        assert first_record.used_at is not None

        assert reset_password(
            db,
            first_token,
            "NewStockPilot_Password_123!",
        ) is False


def test_successful_password_reset_revokes_all_sessions(
    test_environment,
):
    client, session_factory = test_environment
    register_test_user(client)

    with session_factory() as db:
        user = get_test_user(db)

        credentials = LoginRequest(
            email="reset.owner@example.com",
            password="StockPilot_Test_123!",
        )

        login_result = create_login_session(db, credentials)

        assert login_result is not None

        raw_session_token = login_result[1]

        session_hash = hashlib.sha256(
            raw_session_token.encode("utf-8")
        ).hexdigest()

        raw_reset_token = create_password_reset_token(db, user)

        assert reset_password(
            db,
            raw_reset_token,
            "NewStockPilot_Password_123!",
        ) is True

    with session_factory() as db:
        user = get_test_user(db)

        assert verify_password(
            "NewStockPilot_Password_123!",
            user.password_hash,
        )

        assert not verify_password(
            "StockPilot_Test_123!",
            user.password_hash,
        )

        user_session = db.scalar(
            select(UserSession).where(
                UserSession.token_hash == session_hash
            )
        )

        assert user_session is not None
        assert user_session.revoked_at is not None


def test_expired_reset_token_is_rejected(test_environment):
    client, session_factory = test_environment
    register_test_user(client)

    with session_factory() as db:
        user = get_test_user(db)
        raw_token = create_password_reset_token(db, user)

        token_hash = hashlib.sha256(
            raw_token.encode("utf-8")
        ).hexdigest()

        reset_record = db.scalar(
            select(PasswordResetToken).where(
                PasswordResetToken.token_hash == token_hash
            )
        )

        assert reset_record is not None

        reset_record.expires_at = (
            datetime.now(timezone.utc) - timedelta(minutes=5)
        )

        db.commit()

        assert reset_password(
            db,
            raw_token,
            "NewStockPilot_Password_123!",
        ) is False


def test_reset_token_cannot_be_reused(test_environment):
    client, session_factory = test_environment
    register_test_user(client)

    with session_factory() as db:
        user = get_test_user(db)
        raw_token = create_password_reset_token(db, user)

        assert reset_password(
            db,
            raw_token,
            "NewStockPilot_Password_123!",
        ) is True

        assert reset_password(
            db,
            raw_token,
            "AnotherStockPilot_Password_123!",
        ) is False


def test_unknown_reset_token_is_rejected(test_environment):
    client, session_factory = test_environment
    register_test_user(client)

    with session_factory() as db:
        assert reset_password(
            db,
            "this-is-not-a-valid-reset-token",
            "NewStockPilot_Password_123!",
        ) is False



def test_forgot_password_returns_generic_response(
    test_environment,
    monkeypatch,
):
    client, _ = test_environment
    register_test_user(client)

    captured_emails = []

    def fake_send_email(recipient_email, raw_token):
        captured_emails.append({
            "recipient": recipient_email,
            "token": raw_token,
        })

    monkeypatch.setattr(
        "app.api.routes.auth.send_password_reset_email",
        fake_send_email,
    )

    # Registered email.
    registered_response = client.post(
        "/api/v1/auth/forgot-password",
        json={"email": "reset.owner@example.com"},
    )

    # Unknown email.
    unknown_response = client.post(
        "/api/v1/auth/forgot-password",
        json={"email": "unknown@example.com"},
    )

    assert registered_response.status_code == 200
    assert unknown_response.status_code == 200

    assert registered_response.json() == unknown_response.json()

    assert len(captured_emails) == 1
    assert captured_emails[0]["recipient"] == "reset.owner@example.com"

    # The raw token must never appear in the API response.
    assert captured_emails[0]["token"] not in registered_response.text


def test_reset_password_endpoint_revokes_old_session_and_allows_new_login(
    test_environment,
    monkeypatch,
):
    client, _ = test_environment
    register_test_user(client)

    # First, log in using the original password.
    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "reset.owner@example.com",
            "password": "StockPilot_Test_123!",
        },
    )

    assert login_response.status_code == 200

    old_session_token = login_response.cookies.get(
        "stockpilot_session"
    )

    assert old_session_token is not None

    captured_tokens = []

    def fake_send_email(recipient_email, raw_token):
        captured_tokens.append(raw_token)

    monkeypatch.setattr(
        "app.api.routes.auth.send_password_reset_email",
        fake_send_email,
    )

    # Request a password reset.
    forgot_response = client.post(
        "/api/v1/auth/forgot-password",
        json={"email": "reset.owner@example.com"},
    )

    assert forgot_response.status_code == 200
    assert len(captured_tokens) == 1

    # Reset the password using the captured email token.
    new_password = "NewStockPilot_Password_123!"

    reset_response = client.post(
        "/api/v1/auth/reset-password",
        json={
            "token": captured_tokens[0],
            "new_password": new_password,
        },
    )

    assert reset_response.status_code == 200

    assert reset_response.json()["message"] == (
        "Your password has been reset successfully. "
        "Please log in with your new password."
    )

    # The old session must no longer authenticate.
    old_session_response = client.get(
        "/api/v1/auth/me",
        cookies={"stockpilot_session": old_session_token},
    )

    assert old_session_response.status_code == 401

    # The new password must work.
    new_login_response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "reset.owner@example.com",
            "password": new_password,
        },
    )

    assert new_login_response.status_code == 200

    # The old password must no longer work.
    old_password_response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "reset.owner@example.com",
            "password": "StockPilot_Test_123!",
        },
    )

    assert old_password_response.status_code == 401


def test_reset_password_endpoint_rejects_invalid_token(
    test_environment,
):
    client, _ = test_environment
    register_test_user(client)

    response = client.post(
        "/api/v1/auth/reset-password",
        json={
            "token": "invalid-password-reset-token-123456",
            "new_password": "NewStockPilot_Password_123!",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Invalid or expired password reset link."
    )
