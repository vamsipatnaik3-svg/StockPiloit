from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    HTTPException,
    Response,
    status,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    RegistrationRequest,
    RegistrationResponse,
)
from app.services.registration import (
    EmailAlreadyRegistered,
    register_company_owner,
)
from app.services.authentication import (
    create_login_session,
    get_authenticated_user,
    revoke_login_session,
)


router = APIRouter(tags=["Authentication"])


# --------------------------------------------------
# REGISTER
# --------------------------------------------------

@router.post(
    "/register",
    response_model=RegistrationResponse,
    status_code=status.HTTP_201_CREATED,
)
def register(
    registration: RegistrationRequest,
    db: Session = Depends(get_db),
):
    try:
        user, company = register_company_owner(db, registration)

        return RegistrationResponse(
            user_id=str(user.id),
            company_id=str(company.id),
            company_name=company.name,
            user_email=user.email,
            role="OWNER",
        )

    except EmailAlreadyRegistered as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )

    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to complete registration.",
        )


# --------------------------------------------------
# LOGIN
# --------------------------------------------------

@router.post(
    "/login",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
)
def login(
    credentials: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    try:
        result = create_login_session(db, credentials)

    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to complete login.",
        )

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    user, raw_token = result

    response.set_cookie(
        key="stockpilot_session",
        value=raw_token,
        httponly=True,
        secure=False,
        samesite="lax",
        max_age=7 * 24 * 60 * 60,
        path="/",
    )

    return LoginResponse(
        user_id=str(user.id),
        full_name=user.full_name,
        email=user.email,
    )


# --------------------------------------------------
# CURRENT AUTHENTICATED USER
# --------------------------------------------------

@router.get(
    "/me",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
)
def get_current_user(
    stockpilot_session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    if not stockpilot_session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )

    try:
        user = get_authenticated_user(db, stockpilot_session)

    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to verify authentication.",
        )

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session.",
        )

    return LoginResponse(
        user_id=str(user.id),
        full_name=user.full_name,
        email=user.email,
    )


# --------------------------------------------------
# LOGOUT
# --------------------------------------------------

@router.post(
    "/logout",
    status_code=status.HTTP_200_OK,
)
def logout(
    response: Response,
    stockpilot_session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    if stockpilot_session:
        try:
            revoke_login_session(db, stockpilot_session)

        except SQLAlchemyError:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Unable to complete logout.",
            )

    response.delete_cookie(
        key="stockpilot_session",
        path="/",
        httponly=True,
        secure=False,
        samesite="lax",
    )

    return {
        "message": "Successfully logged out."
    }
