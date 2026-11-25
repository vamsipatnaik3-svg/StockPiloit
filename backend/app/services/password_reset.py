
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models import PasswordResetToken, User, UserSession


PASSWORD_RESET_DURATION_MINUTES = 30


def _hash_token(raw_token: str) -> str:
    """Return the SHA-256 hash of a reset token."""
    return hashlib.sha256(
        raw_token.encode("utf-8")
    ).hexdigest()


def create_password_reset_token(
    db: Session,
    user: User,
) -> str:
    """
    Create a new password reset token.

    Previous unused tokens for this user are invalidated.
    Only the SHA-256 hash is stored in the database.

    Returns the raw token for email delivery.
    """
    now = datetime.now(timezone.utc)

    db.execute(
        update(PasswordResetToken)
        .where(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.used_at.is_(None),
        )
        .values(used_at=now)
        .execution_options(synchronize_session=False)
    )

    raw_token = secrets.token_urlsafe(32)

    reset_token = PasswordResetToken(
        user_id=user.id,
        token_hash=_hash_token(raw_token),
        expires_at=now + timedelta(
            minutes=PASSWORD_RESET_DURATION_MINUTES
        ),
        created_at=now,
    )

    db.add(reset_token)
    db.commit()

    return raw_token


def reset_password(
    db: Session,
    raw_token: str,
    new_password: str,
) -> bool:
    """
    Validate a reset token and update the user's password.

    A token can only be consumed once.
    All active login sessions are revoked after a successful reset.

    Returns True on success, otherwise False.
    """
    now = datetime.now(timezone.utc)
    token_hash = _hash_token(raw_token)

    reset_token = db.scalar(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == token_hash
        )
    )

    if reset_token is None:
        return False

    if reset_token.used_at is not None:
        return False

    expires_at = reset_token.expires_at

    # SQLite may return a naive datetime in tests.
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if expires_at <= now:
        return False

    user = db.get(User, reset_token.user_id)

    if user is None or not user.is_active:
        return False

    # The database evaluates the conditions. This avoids Python-side
    # comparisons between naive and aware datetime values in SQLite.
    claim_result = db.execute(
        update(PasswordResetToken)
        .where(
            PasswordResetToken.id == reset_token.id,
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at > now,
        )
        .values(used_at=now)
        .execution_options(synchronize_session=False)
    )

    if claim_result.rowcount != 1:
        db.rollback()
        return False

    user.password_hash = hash_password(new_password)

    db.execute(
        update(UserSession)
        .where(
            UserSession.user_id == user.id,
            UserSession.revoked_at.is_(None),
        )
        .values(revoked_at=now)
        .execution_options(synchronize_session=False)
    )

    # Token consumption, password update and session revocation
    # succeed or fail together.
    db.commit()

    return True
