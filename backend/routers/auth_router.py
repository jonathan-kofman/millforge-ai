"""
/api/auth endpoints – user registration, login, logout, and session check.
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
    MeResponse,
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


def _set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key="millforge_session",
        value=token,
        httponly=True,
        secure=_COOKIE_SECURE,
        samesite=_COOKIE_SAMESITE,
        max_age=_COOKIE_MAX_AGE,
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
    _set_auth_cookie(response, token)
    logger.info(f"User logged in: {user.email}")

    return LoginResponse(
        access_token=token,
        token_type="bearer",
        user_id=user.id,
        email=user.email,
        name=user.name,
        company=user.company,
    )


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
