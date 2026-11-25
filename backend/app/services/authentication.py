
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import verify_password
from app.models import User, UserSession
from app.schemas.auth import LoginRequest


SESSION_DURATION_DAYS = 7


def create_login_session(
    db: Session,
    credentials: LoginRequest,
) -> tuple[User, str] | None:

    email = str(credentials.email).strip().lower()

    # Find the user by email.
    user = db.scalar(
        select(User).where(User.email == email)
    )

    # Use the same error outcome for unknown email and wrong password.
    if user is None:
        return None

    if not verify_password(
        credentials.password,
        user.password_hash,
    ):
        return None

    # Do not allow inactive accounts to log in.
    if not user.is_active:
        return None

    # Generate a cryptographically secure random session token.
    raw_token = secrets.token_urlsafe(32)

    # Store only the SHA-256 hash in the database.
    token_hash = hashlib.sha256(
        raw_token.encode("utf-8")
    ).hexdigest()

    now = datetime.now(timezone.utc)

    user_session = UserSession(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=now + timedelta(days=SESSION_DURATION_DAYS),
        created_at=now,
    )

    db.add(user_session)
    db.commit()

    return user, raw_token


def get_authenticated_user(
    db: Session,
    raw_token: str,
) -> User | None:

    # Hash the token received from the browser.
    token_hash = hashlib.sha256(
        raw_token.encode("utf-8")
    ).hexdigest()

    # Find the matching session.
    user_session = db.scalar(
        select(UserSession).where(
            UserSession.token_hash == token_hash
        )
    )

    if user_session is None:
        return None

    # Reject revoked sessions.
    if user_session.revoked_at is not None:
        return None

    now = datetime.now(timezone.utc)
    expires_at = user_session.expires_at

    # SQLite may return a naive datetime in tests.
    # Treat it as UTC because we originally stored UTC.
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    # Reject expired sessions and revoke them.
    if expires_at <= now:
        user_session.revoked_at = now
        db.commit()
        return None

    # Find the user associated with the session.
    user = db.get(User, user_session.user_id)

    if user is None or not user.is_active:
        return None

    return user

def revoke_login_session(
    db: Session,
    raw_token: str,
) -> bool:
    """Revoke an active login session."""

    token_hash = hashlib.sha256(
        raw_token.encode("utf-8")
    ).hexdigest()

    user_session = db.scalar(
        select(UserSession).where(
            UserSession.token_hash == token_hash
        )
    )

    if user_session is None:
        return False

    if user_session.revoked_at is not None:
        return False

    user_session.revoked_at = datetime.now(timezone.utc)
    db.commit()

    return True