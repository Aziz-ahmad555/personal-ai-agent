import uuid
from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.schemas import ApprovalDecision, AuditLogRead
from app.audit.service import ApprovalError
from app.auth.account_deletion import (
    decide_and_execute_account_deletion,
    request_account_deletion,
)
from app.auth.deps import any_users_exist, get_current_user
from app.auth.schemas import (
    AccountDeletionResult,
    RefreshRequest,
    TokenPair,
    UserRead,
    UserRegister,
)
from app.auth.security import create_token, decode_token, hash_password, verify_password
from app.core.demo import DEMO_USER_EMAIL, require_demo_mode, require_not_demo_mode
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


@router.post("/demo-login", response_model=TokenPair, dependencies=[Depends(require_demo_mode)])
async def demo_login(db: Annotated[AsyncSession, Depends(get_db)]) -> TokenPair:
    """Demo-mode-only (404s otherwise, see require_demo_mode): issues a real token pair for
    the one pre-seeded demo user, no password exchange — there's no real credential to
    protect here, since a visitor reaching this at all already means demo_mode is on and
    nothing behind this login is anyone's real account. scripts/seed_demo.py creates this
    user; if it hasn't run yet, this fails clearly rather than silently creating one."""
    result = await db.execute(select(User).where(User.email == DEMO_USER_EMAIL))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Demo account not seeded yet.",
        )
    logger.info("demo_user_logged_in", user_id=str(user.id))
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


@router.post(
    "/delete-account/request",
    response_model=AuditLogRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_not_demo_mode)],
)
async def request_delete_account(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AuditLogRead:
    """Files a red-risk request to permanently delete every record this account owns and
    revoke every connected integration at its provider — a genuine full-account wipe, not a
    per-integration disconnect. Returns the pending approval with a live evidence snapshot
    (row counts, connection statuses) for the frontend to show as the confirmation screen.
    Nothing is deleted until /delete-account/{id}/decide is called with approved=true."""
    log = await request_account_deletion(db, user=current_user)
    await db.commit()
    await db.refresh(log)
    return AuditLogRead.model_validate(log)


@router.post(
    "/delete-account/{log_id}/decide",
    response_model=AccountDeletionResult,
    dependencies=[Depends(require_not_demo_mode)],
)
async def decide_delete_account(
    log_id: uuid.UUID,
    body: ApprovalDecision,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AccountDeletionResult:
    """The user's second, explicit confirmation. Declining leaves the account untouched.
    Approving re-verifies the evidence from /delete-account/request against the database
    right now (the independent second check every red-risk action requires) and refuses if
    it has drifted — then, only if that passes, actually deletes the account in this same
    call. There is no further step after a successful approval: the account (and the access
    token this request is authenticated with) no longer exists."""
    try:
        result = await decide_and_execute_account_deletion(
            db, audit_log_id=log_id, user=current_user, approved=body.approved
        )
    except ApprovalError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return AccountDeletionResult.model_validate(result)
