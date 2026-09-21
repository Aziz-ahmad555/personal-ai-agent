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
from app.config import get_settings
from app.db import base as db_base
from app.db.base import get_db
from app.db.models import User
from app.github import oauth
from app.github.client import GithubApiError, get_authenticated_user, list_installations
from app.github.models import (
    GithubConnection,
    GithubRepo,
    GithubSkillProposal,
    GithubSyncRun,
)
from app.github.schemas import ConnectionRead, DisconnectResult
from app.github.service import write_permissions
from app.gmail.crypto import decrypt_token, encrypt_token
from app.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/github", tags=["github"])

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


async def _get_connection(db: AsyncSession, user_id: uuid.UUID) -> GithubConnection:
    result = await db.execute(select(GithubConnection).where(GithubConnection.user_id == user_id))
    connection = result.scalar_one_or_none()
    if connection is None:
        raise _NOT_FOUND
    return connection


def _redirect(**params: str) -> RedirectResponse:
    return RedirectResponse(f"{get_settings().github_frontend_return_url}?{urlencode(params)}")


@router.get("/connection", response_model=ConnectionRead)
async def get_connection(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> GithubConnection:
    return await _get_connection(db, current_user.id)


@router.get("/oauth/start")
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


@router.get("/oauth/callback")
async def oauth_callback(request: Request) -> RedirectResponse:
    """Hit by the browser on GitHub's redirect. There's no Bearer token here, so the signed
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
            account = await get_authenticated_user(client, tokens.access_token)
            installations = await list_installations(client, tokens.access_token)
    except (oauth.OAuthError, GithubApiError) as exc:
        logger.warning("github_oauth_callback_failed", error=str(exc))
        await _audit_failure(user_id, str(exc))
        return _redirect(error=str(exc))

    writable = write_permissions(installations)
    if writable:
        # The integration is read-only by design. Refuse, and invalidate the token we just got.
        await oauth.revoke_token(tokens.access_token)
        message = (
            "This GitHub App has write permissions "
            f"({', '.join(writable)}). Remove them on GitHub and connect again."
        )
        await _audit_failure(user_id, message)
        return _redirect(error=message)

    async with db_base.async_session_factory() as db:
        connection = (
            await db.execute(select(GithubConnection).where(GithubConnection.user_id == user_id))
        ).scalar_one_or_none()
        previous_login = connection.github_login if connection else None
        if connection is None:
            connection = GithubConnection(
                user_id=user_id,
                github_login=account["login"],
                github_user_id=account["id"],
            )
            db.add(connection)

        connection.github_login = account["login"]
        connection.github_user_id = account["id"]
        connection.access_token_encrypted = encrypt_token(tokens.access_token)
        connection.refresh_token_encrypted = (
            encrypt_token(tokens.refresh_token) if tokens.refresh_token else None
        )
        connection.token_expires_at = tokens.expires_at
        connection.refresh_token_expires_at = tokens.refresh_expires_at
        connection.installations = installations
        connection.status = "connected"
        connection.last_error = None
        await db.flush()
        await log_action(
            db,
            user_id=user_id,
            action="github.connected",
            risk_level="green",
            summary=f"Connected GitHub account {account['login']} (read-only).",
            evidence={
                "github_login": account["login"],
                "previous_login": previous_login,
                "installations": installations,
                "write_permissions": [],
            },
            resource_type="github_connection",
            resource_id=connection.id,
        )
        await db.commit()

    return _redirect(connected="1")


async def _audit_failure(user_id: uuid.UUID, error: str) -> None:
    async with db_base.async_session_factory() as db:
        await log_action(
            db,
            user_id=user_id,
            action="github.connect_failed",
            risk_level="green",
            summary="Connecting GitHub did not complete.",
            error=error,
        )
        await db.commit()


@router.delete("/connection", response_model=DisconnectResult)
async def disconnect(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    purge_data: Annotated[bool, Query()] = False,
) -> DisconnectResult:
    """Skills already added to the profile are the user's own and are never removed here; only
    the synced snapshot, sync history and proposals are deleted when `purge_data` is set."""
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
    connection.refresh_token_expires_at = None
    if purge_data:
        for model in (GithubRepo, GithubSkillProposal, GithubSyncRun):
            await db.execute(delete(model).where(model.connection_id == connection.id))
    await log_action(
        db,
        user_id=current_user.id,
        action="github.disconnected",
        risk_level="green",
        summary=f"Disconnected GitHub account {connection.github_login}.",
        evidence={"revoked_at_github": revoked, "purged_synced_data": purge_data},
        resource_type="github_connection",
        resource_id=connection.id,
    )
    await db.commit()
    await db.refresh(connection)
    return DisconnectResult(
        connection=ConnectionRead.model_validate(connection), revoked_at_github=revoked
    )
