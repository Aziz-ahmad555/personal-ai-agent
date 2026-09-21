"""Connection logic shared by the router and (later) sync: the read-only guard and
token lifecycle."""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.github import oauth
from app.github.models import GithubConnection
from app.gmail.crypto import decrypt_token, encrypt_token

_WRITE_LEVELS = {"write", "admin"}
_REFRESH_MARGIN = timedelta(seconds=60)


class NotConnectedError(RuntimeError):
    """There's no usable GitHub connection (never connected, disconnected, or needs reauth)."""


def write_permissions(installations: list[dict[str, Any]]) -> list[str]:
    """Permissions in any installation that allow writing, as "permission:level". Empty for a
    correctly registered app. The connect flow refuses to proceed if this isn't empty, so the
    integration stays read-only even if the app is later given more access on GitHub."""
    found: list[str] = []
    for installation in installations:
        for name, level in (installation.get("permissions") or {}).items():
            if level in _WRITE_LEVELS:
                found.append(f"{name}:{level}")
    return sorted(set(found))


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


async def get_valid_access_token(db: AsyncSession, connection: GithubConnection) -> str:
    """A working access token, refreshing (and persisting the rotated tokens) when it is
    about to expire. Marks the connection needs_reauth if GitHub refuses the refresh."""
    if connection.status != "connected" or not connection.access_token_encrypted:
        raise NotConnectedError("GitHub isn't connected — connect it first.")

    expires_at = _aware(connection.token_expires_at)
    if expires_at is None or expires_at - _REFRESH_MARGIN > datetime.now(UTC):
        return decrypt_token(connection.access_token_encrypted)

    if not connection.refresh_token_encrypted:
        await _mark_needs_reauth(db, connection, "GitHub access has expired.")
        raise NotConnectedError("GitHub access has expired — reconnect it.")

    try:
        tokens = await oauth.refresh_access_token(decrypt_token(connection.refresh_token_encrypted))
    except oauth.ReauthRequiredError as exc:
        await _mark_needs_reauth(db, connection, str(exc))
        raise NotConnectedError("GitHub access has expired — reconnect it.") from exc

    connection.access_token_encrypted = encrypt_token(tokens.access_token)
    connection.token_expires_at = tokens.expires_at
    if tokens.refresh_token:  # GitHub rotates it; the old one is now dead
        connection.refresh_token_encrypted = encrypt_token(tokens.refresh_token)
        connection.refresh_token_expires_at = tokens.refresh_expires_at
    await db.commit()
    return tokens.access_token


async def _mark_needs_reauth(db: AsyncSession, connection: GithubConnection, reason: str) -> None:
    connection.status = "needs_reauth"
    connection.last_error = reason
    await db.commit()
