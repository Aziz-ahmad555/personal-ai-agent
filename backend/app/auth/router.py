from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import any_users_exist, get_current_user
from app.auth.schemas import RefreshRequest, TokenPair, UserRead, UserRegister
from app.auth.security import create_token, decode_token, hash_password, verify_password
from app.core.rate_limit import limiter
from app.db.base import get_db
from app.db.models import User
from app.logging import get_logger

router = APIRouter(prefix="/auth", tags=["auth"])
logger = get_logger(__name__)

# Both endpoints are the one place an unauthenticated caller can make the server do repeated
# work tied to a guessable identity (an email address) — a credential-stuffing / brute-force
# surface. Limited per-IP; 5/minute is generous for a real human, tight for a script.
LOGIN_RATE_LIMIT = "5/minute"


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
@limiter.limit(LOGIN_RATE_LIMIT)
async def register(
    request: Request,
    payload: UserRegister,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Bootstrap-only: creates the first user. Once any user exists, this is disabled —
    this is a single-user personal agent, not a multi-tenant signup flow."""
    if await any_users_exist(db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Registration is closed: an owner account already exists.",
        )

    user = User(
        email=payload.email.lower(),
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    logger.info("user_registered", user_id=str(user.id))
    return user


@router.post("/login", response_model=TokenPair)
@limiter.limit(LOGIN_RATE_LIMIT)
async def login(
    request: Request,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenPair:
    result = await db.execute(select(User).where(User.email == form_data.username.lower()))
    user = result.scalar_one_or_none()

    if user is None or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled")

    logger.info("user_logged_in", user_id=str(user.id))
    return TokenPair(
        access_token=create_token(user.id, "access"),
        refresh_token=create_token(user.id, "refresh"),
    )


@router.post("/refresh", response_model=TokenPair)
async def refresh(
    payload: RefreshRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenPair:
    """KNOWN GAP, deliberately deferred (Phase 10 red-team pass, 2026-09-23): no refresh-token
    rotation. The token presented here is not invalidated after use, so it stays valid — and
    replayable — until its own expiry (REFRESH_TOKEN_EXPIRE_DAYS). Accepted for now because this
    is a single-user, local-only app (see `register`'s bootstrap-only comment) where the realistic
    threat model doesn't include a network attacker capturing this device's refresh token. A real
    fix needs statefulness this scheme doesn't have today: track issued/used/revoked refresh
    tokens (e.g. a DB table keyed by jti), reject reuse, and rotate on every call.
    MUST be revisited before any public or production deployment, or before this app is ever
    exposed to more than one trusted device. See tests/test_redteam_auth.py::
    test_FINDING_a_refresh_token_is_reusable_after_being_used for the regression test that
    currently documents (not enforces) this gap.
    """
    try:
        user_id = decode_token(payload.refresh_token, expected_type="refresh")
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        ) from exc

    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        )

    return TokenPair(
        access_token=create_token(user.id, "access"),
        refresh_token=create_token(user.id, "refresh"),
    )


@router.get("/me", response_model=UserRead)
async def me(current_user: Annotated[User, Depends(get_current_user)]) -> User:
    return current_user
