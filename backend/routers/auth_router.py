"""
/api/auth endpoints – user registration and login.
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from database import get_db
from db_models import User
from auth.jwt_utils import hash_password, verify_password, create_access_token
from models.schemas import (
    RegisterRequest, RegisterResponse,
    LoginRequest, LoginResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["Auth"])


@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
async def register(req: RegisterRequest, db: Session = Depends(get_db)) -> RegisterResponse:
    """
    Register a new user account.

    Email must be unique. Password is bcrypt-hashed before storage.
    Returns a JWT access token so the client is immediately logged in.
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
    logger.info(f"New user registered: {user.email}")

    return RegisterResponse(
        access_token=token,
        token_type="bearer",
        user_id=user.id,
        email=user.email,
        name=user.name,
    )


@router.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    """
    Authenticate with email and password, receive a JWT access token.
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
    logger.info(f"User logged in: {user.email}")

    return LoginResponse(
        access_token=token,
        token_type="bearer",
        user_id=user.id,
        email=user.email,
        name=user.name,
        company=user.company,
    )
