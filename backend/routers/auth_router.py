"""
/api/auth endpoints – user registration, login, logout, session check, and password reset.
"""

import logging
import os as _os
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from database import get_db
from db_models import User
from auth.jwt_utils import hash_password, verify_password, create_access_token
from auth.dependencies import get_current_user
from models.schemas import (
    RegisterRequest, RegisterResponse,
    LoginRequest, LoginResponse,
    MeResponse, ForgotPasswordRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["Auth"])
limiter = Limiter(key_func=get_remote_address)

_REGISTER_LIMIT = _os.getenv("AUTH_REGISTER_RATE_LIMIT", "10/hour")
_LOGIN_LIMIT    = _os.getenv("AUTH_LOGIN_RATE_LIMIT",    "20/hour")

# Cookie settings: use secure/SameSite=none for cross-origin prod (Railway ↔ Vercel),
# lax/insecure for local dev where Vite proxies /api to :8000 (same-origin).
_COOKIE_SECURE   = bool(_os.getenv("RAILWAY_ENVIRONMENT") or _os.getenv("COOKIE_SECURE"))
_COOKIE_SAMESITE = "none" if _COOKIE_SECURE else "lax"
_COOKIE_MAX_AGE  = int(_os.getenv("ACCESS_TOKEN_EXPIRE_HOURS", "24")) * 3600
_REMEMBER_ME_MAX_AGE = 30 * 24 * 3600  # 30 days


def _set_auth_cookie(response: Response, token: str, remember_me: bool = False) -> None:
    response.set_cookie(
        key="millforge_session",
        value=token,
        httponly=True,
        secure=_COOKIE_SECURE,
        samesite=_COOKIE_SAMESITE,
        max_age=_REMEMBER_ME_MAX_AGE if remember_me else _COOKIE_MAX_AGE,
        path="/",
    )


@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(_REGISTER_LIMIT)
async def register(
    request: Request,
    req: RegisterRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> RegisterResponse:
    """
    Register a new user account.

    Email must be unique. Password is argon2-hashed before storage.
    Sets an httpOnly session cookie and returns user info.
    """
    if db.query(User).filter(User.email == req.email.lower()).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )

    user = User(
        email=req.email.lower().strip(),
        hashed_password=hash_password(req.password),
        name=req.name,
        company=req.company,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(user.email, user.id)
    _set_auth_cookie(response, token)
    logger.info(f"New user registered: {user.email}")

    return RegisterResponse(
        access_token=token,
        token_type="bearer",
        user_id=user.id,
        email=user.email,
        name=user.name,
    )


@router.post("/login", response_model=LoginResponse)
@limiter.limit(_LOGIN_LIMIT)
async def login(
    request: Request,
    req: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> LoginResponse:
    """
    Authenticate with email and password.

    Sets an httpOnly session cookie and returns user info.
    Pass remember_me=true for a 30-day cookie instead of the default 24-hour session.
    """
    user = db.query(User).filter(User.email == req.email.lower()).first()
    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive",
        )

    token = create_access_token(user.email, user.id)
    _set_auth_cookie(response, token, remember_me=req.remember_me)
    logger.info(f"User logged in: {user.email} (remember_me={req.remember_me})")

    return LoginResponse(
        access_token=token,
        token_type="bearer",
        user_id=user.id,
        email=user.email,
        name=user.name,
        company=user.company,
    )


@router.post("/forgot-password", status_code=status.HTTP_200_OK)
@limiter.limit("5/hour")
async def forgot_password(
    request: Request,
    req: ForgotPasswordRequest,
    db: Session = Depends(get_db),
) -> dict:
    """
    Request a password reset link.

    Always returns 200 to prevent email enumeration — even if the email
    doesn't exist. The actual reset email requires an email provider (Resend,
    SendGrid, etc.) to be configured via SMTP_* env vars.
    """
    user = db.query(User).filter(User.email == req.email.lower()).first()
    if user:
        # TODO: generate a signed reset token and send via email service
        # token = create_reset_token(user.email)
        # send_reset_email(user.email, token)
        logger.info(f"Password reset requested for: {user.email}")
    else:
        logger.info(f"Password reset requested for non-existent email: {req.email}")

    return {"message": "If an account with that email exists, a reset link has been sent."}


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response) -> None:
    """Clear the session cookie."""
    response.delete_cookie(
        key="millforge_session",
        path="/",
        samesite=_COOKIE_SAMESITE,
        secure=_COOKIE_SECURE,
    )


@router.get("/me", response_model=MeResponse)
async def me(user: User = Depends(get_current_user)) -> MeResponse:
    """Return the currently authenticated user's profile."""
    return MeResponse(
        user_id=user.id,
        email=user.email,
        name=user.name,
        company=user.company,
    )
