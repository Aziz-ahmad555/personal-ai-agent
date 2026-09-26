import uuid
from typing import Annotated

import httpx
import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.config import get_settings
from app.db import base as db_base
from app.db.base import get_db
from app.db.models import User
from app.gmail import oauth
from app.gmail.client import GmailApiError, get_profile
from app.gmail.crypto import decrypt_token, encrypt_token
from app.gmail.models import EmailMessage, GmailConnection, GmailSyncRun
from app.gmail.oauth import (
    OAuthError,
    build_authorization_url,
    exchange_code_for_tokens,
    verify_state,
)
from app.gmail.schemas import ConnectionRead, DisconnectRequest, EmailMessageRead, SyncRunRead
from app.gmail.sync import run_sync
from app.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/gmail", tags=["gmail"])

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


async def _get_connection(db: AsyncSession, user_id: uuid.UUID) -> GmailConnection:
    result = await db.execute(select(GmailConnection).where(GmailConnection.user_id == user_id))
    connection = result.scalar_one_or_none()
    if connection is None:
        raise _NOT_FOUND
    return connection


@router.get("/connection", response_model=ConnectionRead)
async def get_connection(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> GmailConnection:
    return await _get_connection(db, current_user.id)


@router.get("/oauth/start")
async def oauth_start(
    current_user: Annotated[User, Depends(get_current_user)],
) -> dict[str, str]:
    try:
        url = build_authorization_url(current_user.id)
    except OAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    return {"authorization_url": url}


@router.get("/oauth/callback")
async def oauth_callback(request: Request) -> RedirectResponse:
    """Hit directly by the browser on Google's redirect — no Bearer token available here,
    so the signed `state` param (not a cookie/session) is what identifies the user."""
    settings = get_settings()
    return_url = settings.gmail_frontend_return_url

    error_param = request.query_params.get("error")
    if error_param:
        return RedirectResponse(f"{return_url}?error={error_param}")

    code = request.query_params.get("code")
    state = request.query_params.get("state")
    if not code or not state:
        return RedirectResponse(f"{return_url}?error=missing_code_or_state")

    try:
        user_id = verify_state(state)
        tokens = await exchange_code_for_tokens(code)

        async with httpx.AsyncClient(timeout=15.0) as client:
            profile = await get_profile(client, tokens.access_token)
        google_email = str(profile.get("emailAddress", ""))
    except (OAuthError, GmailApiError) as exc:
        logger.warning("gmail_oauth_callback_failed", error=str(exc))
        return RedirectResponse(f"{return_url}?error={exc}")

    async with db_base.async_session_factory() as db:
        existing = await db.execute(
            select(GmailConnection).where(GmailConnection.user_id == user_id)
        )
        connection = existing.scalar_one_or_none()
        if connection is None:
            connection = GmailConnection(
                user_id=user_id, google_email=google_email, granted_scopes=""
            )
            db.add(connection)

        connection.google_email = google_email
        connection.access_token_encrypted = encrypt_token(tokens.access_token)
        connection.refresh_token_encrypted = encrypt_token(tokens.refresh_token)  # type: ignore[arg-type]
        connection.token_expires_at = tokens.expires_at
        connection.granted_scopes = tokens.granted_scopes
        connection.status = "connected"
        connection.last_sync_error = None
        await db.commit()

    return RedirectResponse(f"{return_url}?connected=1")


async def _run_sync_in_background(sync_run_id: uuid.UUID) -> None:
    structlog.contextvars.bind_contextvars(task_id=str(sync_run_id))
    async with db_base.async_session_factory() as db:
        await run_sync(db, sync_run_id)


@router.post("/sync", response_model=SyncRunRead, status_code=status.HTTP_201_CREATED)
async def start_sync(
    background_tasks: BackgroundTasks,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> GmailSyncRun:
    connection = await _get_connection(db, current_user.id)
    if connection.status == "needs_reauth":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Gmail access has expired — reconnect before syncing.",
        )
    if connection.status == "disconnected":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Gmail is disconnected — reconnect first."
        )

    sync_type = "backfill" if connection.last_history_id is None else "incremental"
    sync_run = GmailSyncRun(connection_id=connection.id, sync_type=sync_type, status="pending")
    db.add(sync_run)
    await db.commit()
    await db.refresh(sync_run)

    background_tasks.add_task(_run_sync_in_background, sync_run.id)
    return sync_run


@router.get("/sync", response_model=list[SyncRunRead])
async def list_sync_runs(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[GmailSyncRun]:
    connection = await _get_connection(db, current_user.id)
    result = await db.execute(
        select(GmailSyncRun)
        .where(GmailSyncRun.connection_id == connection.id)
        .order_by(GmailSyncRun.started_at.desc())
        .limit(20)
    )
    return list(result.scalars())


@router.get("/sync/{sync_run_id}", response_model=SyncRunRead)
async def get_sync_run(
    sync_run_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> GmailSyncRun:
    connection = await _get_connection(db, current_user.id)
    result = await db.execute(
        select(GmailSyncRun).where(
            GmailSyncRun.id == sync_run_id, GmailSyncRun.connection_id == connection.id
        )
    )
    sync_run = result.scalar_one_or_none()
    if sync_run is None:
        raise _NOT_FOUND
    return sync_run


@router.get("/messages", response_model=list[EmailMessageRead])
async def list_messages(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[EmailMessage]:
    connection = await _get_connection(db, current_user.id)
    result = await db.execute(
        select(EmailMessage)
        .where(EmailMessage.connection_id == connection.id)
        .order_by(EmailMessage.date.desc().nulls_last())
        .limit(limit)
    )
    return list(result.scalars())


@router.delete("/connection", response_model=ConnectionRead)
async def disconnect(
    payload: DisconnectRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> GmailConnection:
    connection = await _get_connection(db, current_user.id)

    # Previously this only cleared the tokens locally and never told Google to invalidate
    # the grant — the same revoke Calendar/GitHub's own disconnect already does. Revoking the
    # refresh token (preferred when present) invalidates the whole grant, not just one
    # access token.
    token_to_revoke = connection.refresh_token_encrypted or connection.access_token_encrypted
    if token_to_revoke:
        try:
            await oauth.revoke_token(decrypt_token(token_to_revoke))
        except Exception:  # noqa: BLE001 — an undecryptable token must not block disconnecting
            pass

    connection.status = "disconnected"
    connection.access_token_encrypted = None
    connection.refresh_token_encrypted = None
    connection.token_expires_at = None
    connection.last_history_id = None

    if payload.purge_data:
        await db.execute(delete(EmailMessage).where(EmailMessage.connection_id == connection.id))

    await db.commit()
    await db.refresh(connection)
    return connection
