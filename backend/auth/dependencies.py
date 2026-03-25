"""
FastAPI dependency functions for authentication.

Token extraction order: httpOnly cookie ("millforge_session") first,
then Authorization: Bearer header as fallback (for API clients / tests).

Usage in routes:
    @router.get("/protected")
    async def protected(user: User = Depends(get_current_user)):
        ...

    @router.get("/optional")
    async def optional(user = Depends(get_current_user_optional)):
        # user is None if not authenticated
        ...
"""

from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from database import get_db
from db_models import User
from .jwt_utils import decode_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


def _extract_token(
    request: Request,
    bearer: Optional[str] = Depends(oauth2_scheme),
) -> Optional[str]:
    """Cookie takes precedence over Bearer header."""
    return request.cookies.get("millforge_session") or bearer


def get_current_user(
    token: Optional[str] = Depends(_extract_token),
    db: Session = Depends(get_db),
) -> User:
    """Require a valid JWT. Raises 401 if missing or invalid."""
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = db.query(User).filter(User.email == payload["sub"]).first()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )
    return user


def get_current_user_optional(
    token: Optional[str] = Depends(_extract_token),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """Return the current user if authenticated, or None. Does not raise."""
    if not token:
        return None
    payload = decode_token(token)
    if payload is None:
        return None
    return db.query(User).filter(User.email == payload["sub"]).first()
