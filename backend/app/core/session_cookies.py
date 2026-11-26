from fastapi import Response

from app.core.config import settings


SESSION_COOKIE_NAME = "stockpilot_session"
SESSION_COOKIE_MAX_AGE = 7 * 24 * 60 * 60
SESSION_COOKIE_SAMESITE = "lax"
SESSION_COOKIE_PATH = "/"


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite=SESSION_COOKIE_SAMESITE,
        max_age=SESSION_COOKIE_MAX_AGE,
        path=SESSION_COOKIE_PATH,
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path=SESSION_COOKIE_PATH,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite=SESSION_COOKIE_SAMESITE,
    )
