
import logging

from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    HTTPException,
    Request,
    Response,
    status,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.dependencies import (
    get_current_user as get_authenticated_current_user,
    get_current_membership,
)
from app.core.rate_limit import enforce_rate_limit
from app.db.session import get_db
from app.models import Company, CompanyMembership, User
from app.schemas.auth import (
    CurrentUserResponse,
    ForgotPasswordRequest,
    LoginRequest,
    LoginResponse,
    PasswordResetResponse,
    RegistrationRequest,
    RegistrationResponse,
    ResetPasswordRequest,
)
from app.services.registration import (
    EmailAlreadyRegistered,
    register_company_owner,
)
from app.services.authentication import (
    create_login_session,
    revoke_login_session,
)
from app.services.password_reset import (
    create_password_reset_token,
    reset_password,
)
from app.services.email import send_password_reset_email


logger = logging.getLogger(__name__)

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
    response_model=CurrentUserResponse,
    status_code=status.HTTP_200_OK,
)
def get_current_user_details(
    user: User = Depends(get_authenticated_current_user),
    membership: CompanyMembership = Depends(get_current_membership),
    db: Session = Depends(get_db),
):
    try:
        company = db.get(Company, membership.company_id)

    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to retrieve company information.",
        )

    if company is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found.",
        )

    return CurrentUserResponse(
        user_id=str(user.id),
        full_name=user.full_name,
        email=user.email,
        company_id=str(company.id),
        company_name=company.name,
        role=membership.role,
    )


# --------------------------------------------------
# FORGOT PASSWORD
# --------------------------------------------------

@router.post(
    "/forgot-password",
    response_model=PasswordResetResponse,
    status_code=status.HTTP_200_OK,
)
def forgot_password(
    http_request: Request,
    request: ForgotPasswordRequest,
    db: Session = Depends(get_db),
):
    # Maximum 5 requests per IP per hour.
    enforce_rate_limit(
        request=http_request,
        action="forgot-password",
        limit=5,
        window_seconds=3600,
    )

    generic_response = PasswordResetResponse(
        message=(
            "If an account exists with that email address, "
            "a password reset link will be sent."
        )
    )

    try:
        user = db.scalar(
            select(User).where(
                User.email == str(request.email).strip().lower()
            )
        )

        # Do not reveal whether an account exists or is active.
        if user is None or not user.is_active:
            return generic_response

        raw_token = create_password_reset_token(db, user)

    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to process your request.",
        )

    # Email failure must not reveal whether the account exists.
    # Never log the token or the reset URL.
    try:
        send_password_reset_email(
            recipient_email=user.email,
            raw_token=raw_token,
        )
    except Exception:
        logger.error("Password reset email delivery failed.")

    return generic_response


# --------------------------------------------------
# RESET PASSWORD
# --------------------------------------------------

@router.post(
    "/reset-password",
    response_model=PasswordResetResponse,
    status_code=status.HTTP_200_OK,
)
def reset_password_endpoint(
    http_request: Request,
    request: ResetPasswordRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    # Maximum 10 attempts per IP per hour.
    enforce_rate_limit(
        request=http_request,
        action="reset-password",
        limit=10,
        window_seconds=3600,
    )

    try:
        successful = reset_password(
            db=db,
            raw_token=request.token,
            new_password=request.new_password,
        )

    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to reset password.",
        )

    if not successful:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired password reset link.",
        )

    # Clear the browser's existing session cookie.
    # All sessions have already been revoked in the database.
    response.delete_cookie(
        key="stockpilot_session",
        path="/",
        httponly=True,
        secure=False,
        samesite="lax",
    )

    return PasswordResetResponse(
        message=(
            "Your password has been reset successfully. "
            "Please log in with your new password."
        )
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
