"""The Calendar connection: OAuth handshake, status, and disconnect.

CAN: read event metadata (title, time, attendees, description) on the user's primary
calendar, once connected, and read it in the background only when the user clicks "Sync
now" (see app/calendar/sync.py). CANNOT: create, edit, or delete anything on the calendar;
read any calendar other than "primary"; act on its own — connecting alone reads nothing
beyond the one identity call needed to show which account is linked.
"""

import uuid
from typing import Annotated
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import log_action
from app.auth.deps import get_current_user
from app.calendar import oauth
from app.calendar.client import CalendarApiError, get_primary_calendar
from app.calendar.models import CalendarConnection, CalendarEvent, CalendarSyncRun
from app.calendar.schemas import ConnectionRead, DisconnectResult
from app.config import get_settings
from app.core.demo import require_not_demo_mode
from app.db import base as db_base
from app.db.base import get_db
from app.db.models import User
from app.gmail.crypto import decrypt_token, encrypt_token
from app.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/calendar", tags=["calendar"])

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


async def _get_connection(db: AsyncSession, user_id: uuid.UUID) -> CalendarConnection:
    result = await db.execute(
        select(CalendarConnection).where(CalendarConnection.user_id == user_id)
    )
    connection = result.scalar_one_or_none()
    if connection is None:
        raise _NOT_FOUND
    return connection


def _redirect(**params: str) -> RedirectResponse:
    return RedirectResponse(f"{get_settings().calendar_frontend_return_url}?{urlencode(params)}")


@router.get("/connection", response_model=ConnectionRead)
async def get_connection(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CalendarConnection:
    return await _get_connection(db, current_user.id)


@router.get("/oauth/start", dependencies=[Depends(require_not_demo_mode)])
async def oauth_start(
    current_user: Annotated[User, Depends(get_current_user)],
) -> dict[str, str]:
    try:
        url = oauth.build_authorization_url(current_user.id)
    except oauth.OAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    return {"authorization_url": url}


@router.get("/oauth/callback", dependencies=[Depends(require_not_demo_mode)])
async def oauth_callback(request: Request) -> RedirectResponse:
    """Hit by the browser on Google's redirect. There's no Bearer token here, so the signed
    `state` (not a cookie) identifies the user."""
    error_param = request.query_params.get("error")
    if error_param:
        return _redirect(error=error_param)

    code = request.query_params.get("code")
    state = request.query_params.get("state")
    if not code or not state:
        return _redirect(error="missing_code_or_state")

    try:
        user_id = oauth.verify_state(state)
    except oauth.OAuthError as exc:
        return _redirect(error=str(exc))

    try:
        tokens = await oauth.exchange_code_for_tokens(code)
        async with httpx.AsyncClient(timeout=15.0) as client:
            calendar = await get_primary_calendar(client, tokens.access_token)
    except (oauth.OAuthError, CalendarApiError) as exc:
        logger.warning("calendar_oauth_callback_failed", error=str(exc))
        await _audit_failure(user_id, str(exc))
        return _redirect(error=str(exc))

    google_email = str(calendar.get("id", ""))
    if not google_email:
        message = "Google's calendar response was missing the account's email."
        await _audit_failure(user_id, message)
        return _redirect(error=message)

    async with db_base.async_session_factory() as db:
        connection = (
            await db.execute(
                select(CalendarConnection).where(CalendarConnection.user_id == user_id)
            )
        ).scalar_one_or_none()
        previous_email = connection.google_email if connection else None
        if connection is None:
            connection = CalendarConnection(
                user_id=user_id, google_email=google_email, granted_scopes=""
            )
            db.add(connection)

        connection.google_email = google_email
        connection.access_token_encrypted = encrypt_token(tokens.access_token)
        connection.refresh_token_encrypted = encrypt_token(tokens.refresh_token)  # type: ignore[arg-type]
        connection.token_expires_at = tokens.expires_at
        connection.granted_scopes = tokens.granted_scopes
        connection.status = "connected"
        connection.last_error = None
        await db.flush()
        await log_action(
            db,
            user_id=user_id,
            action="calendar.connected",
            risk_level="green",
            summary=f"Connected Google Calendar for {google_email} (read-only).",
            evidence={"google_email": google_email, "previous_email": previous_email},
            resource_type="calendar_connection",
            resource_id=connection.id,
        )
        await db.commit()

    return _redirect(connected="1")


async def _audit_failure(user_id: uuid.UUID, error: str) -> None:
    async with db_base.async_session_factory() as db:
        await log_action(
            db,
            user_id=user_id,
            action="calendar.connect_failed",
            risk_level="green",
            summary="Connecting Calendar did not complete.",
            error=error,
        )
        await db.commit()


@router.delete("/connection", response_model=DisconnectResult)
async def disconnect(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    purge_data: Annotated[bool, Query()] = False,
) -> DisconnectResult:
    """Applications you linked an event to are your own and are never removed here; only the
    synced event snapshot and sync history are deleted when `purge_data` is set."""
    connection = await _get_connection(db, current_user.id)

    revoked = False
    if connection.access_token_encrypted:
        try:
            revoked = await oauth.revoke_token(decrypt_token(connection.access_token_encrypted))
        except Exception:  # noqa: BLE001 — an undecryptable token must not block disconnecting
            revoked = False

    connection.status = "disconnected"
    connection.access_token_encrypted = None
    connection.refresh_token_encrypted = None
    connection.token_expires_at = None
    connection.sync_token = None
    if purge_data:
        for model in (CalendarEvent, CalendarSyncRun):
            await db.execute(delete(model).where(model.connection_id == connection.id))
    await log_action(
        db,
        user_id=current_user.id,
        action="calendar.disconnected",
        risk_level="green",
        summary=f"Disconnected Google Calendar for {connection.google_email}.",
        evidence={"revoked_at_google": revoked, "purged_synced_data": purge_data},
        resource_type="calendar_connection",
        resource_id=connection.id,
    )
    await db.commit()
    await db.refresh(connection)
    return DisconnectResult(
        connection=ConnectionRead.model_validate(connection), revoked_at_google=revoked
    )
