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


def test_production_session_cookie_is_secure_and_deletion_matches(test_environment, monkeypatch):
    client, _ = test_environment
    monkeypatch.setattr("app.core.config.settings.app_environment", "production")

    login_response = login_test_user(client)
    set_cookie = login_response.headers["set-cookie"].lower()
    assert "secure" in set_cookie
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie
    assert "path=/" in set_cookie

    logout_response = client.post("/api/v1/auth/logout")
    deleted_cookie = logout_response.headers["set-cookie"].lower()
    assert "stockpilot_session=" in deleted_cookie
    assert "max-age=0" in deleted_cookie
    assert "secure" in deleted_cookie
    assert "httponly" in deleted_cookie
    assert "samesite=lax" in deleted_cookie
    assert "path=/" in deleted_cookie


def test_local_session_cookie_works_over_http(test_environment, monkeypatch):
    client, _ = test_environment
    monkeypatch.setattr("app.core.config.settings.app_environment", "development")

    login_response = login_test_user(client)
    cookie = login_response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "secure" not in cookie
    assert client.get("/api/v1/auth/me").status_code == 200


def test_unknown_email_and_wrong_password_have_same_generic_response(test_environment):
    client, _ = test_environment
    register_test_user(client)

    wrong_password = client.post(
        "/api/v1/auth/login",
        json={"email": "test.owner@example.com", "password": "WrongPassword_123!"},
    )
    unknown_email = client.post(
        "/api/v1/auth/login",
        json={"email": "unknown@example.com", "password": "WrongPassword_123!"},
    )

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()


def test_failed_login_attempts_are_throttled_and_accounts_are_separate(
    test_environment, monkeypatch
):
    from app.core import rate_limit

    client, _ = test_environment
    monkeypatch.setattr(rate_limit.settings, "login_rate_limit_account_ip", 2)
    monkeypatch.setattr(rate_limit.settings, "login_rate_limit_ip", 20)
    monkeypatch.setattr(rate_limit.settings, "login_rate_limit_window_seconds", 900)
    monkeypatch.setattr("app.api.routes.auth.enforce_login_rate_limit", rate_limit.enforce_login_rate_limit)
    monkeypatch.setattr("app.api.routes.auth.record_login_failure", rate_limit.record_login_failure)

    class MemoryRedis:
        def __init__(self):
            self.counts = {}

        def eval(self, script, numkeys, *args):
            keys = args[:numkeys]
            values = args[numkeys:]
            if "GET" in script:
                account_count = self.counts.get(keys[0], 0)
                ip_count = self.counts.get(keys[1], 0)
                account_limit, ip_limit = map(int, values)
                allowed = account_count < account_limit and ip_count < ip_limit
                return [1 if allowed else 0, 0 if allowed else 60]
            self.counts[keys[0]] = self.counts.get(keys[0], 0) + 1
            self.counts[keys[1]] = self.counts.get(keys[1], 0) + 1
            return [self.counts[keys[0]], self.counts[keys[1]]]

    monkeypatch.setattr(rate_limit, "redis_client", MemoryRedis())

    def failed(email):
        return client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "WrongPassword_123!"},
        )

    assert failed("one@example.com").status_code == 401
    assert failed("one@example.com").status_code == 401
    assert failed("ONE@example.com").status_code == 429
    # A distinct normalized account has its own account+IP allowance.
    assert failed("two@example.com").status_code == 401


def test_successful_login_does_not_consume_failed_attempt_allowance(
    test_environment, monkeypatch
):
    from app.core import rate_limit

    client, _ = test_environment
    register_test_user(client)
    monkeypatch.setattr("app.api.routes.auth.enforce_login_rate_limit", rate_limit.enforce_login_rate_limit)
    monkeypatch.setattr("app.api.routes.auth.record_login_failure", rate_limit.record_login_failure)

    class MemoryRedis:
        def __init__(self):
            self.counts = {}

        def eval(self, script, numkeys, *args):
            keys = args[:numkeys]
            if "GET" in script:
                return [1, 0]
            for key in keys:
                self.counts[key] = self.counts.get(key, 0) + 1
            return [1, 1]

    redis = MemoryRedis()
    monkeypatch.setattr(rate_limit, "redis_client", redis)
    response = client.post("/api/v1/auth/login", json=login_payload())

    assert response.status_code == 200
    assert redis.counts == {}


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
