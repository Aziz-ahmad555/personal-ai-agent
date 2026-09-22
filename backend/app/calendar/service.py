"""Connection logic shared by the router and (later) sync: the token lifecycle."""

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.calendar import oauth
from app.calendar.models import CalendarConnection
from app.gmail.crypto import decrypt_token, encrypt_token

_REFRESH_MARGIN = timedelta(seconds=60)


class NotConnectedError(RuntimeError):
    """There's no usable Calendar connection (never connected, disconnected, or needs reauth)."""


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


async def get_valid_access_token(db: AsyncSession, connection: CalendarConnection) -> str:
    """A working access token, refreshing (and persisting it) when it is about to expire.
    Marks the connection needs_reauth if Google refuses the refresh."""
    if connection.status != "connected" or not connection.access_token_encrypted:
        raise NotConnectedError("Calendar isn't connected — connect it first.")

    expires_at = _aware(connection.token_expires_at)
    if expires_at is None or expires_at - _REFRESH_MARGIN > datetime.now(UTC):
        return decrypt_token(connection.access_token_encrypted)

    if not connection.refresh_token_encrypted:
        await _mark_needs_reauth(db, connection, "Calendar access has expired.")
        raise NotConnectedError("Calendar access has expired — reconnect it.")

    try:
        tokens = await oauth.refresh_access_token(decrypt_token(connection.refresh_token_encrypted))
    except oauth.ReauthRequiredError as exc:
        await _mark_needs_reauth(db, connection, str(exc))
        raise NotConnectedError("Calendar access has expired — reconnect it.") from exc

    connection.access_token_encrypted = encrypt_token(tokens.access_token)
    connection.token_expires_at = tokens.expires_at
    # Google's refresh grant doesn't reissue a refresh_token; the original stays valid.
    await db.commit()
    return tokens.access_token


async def _mark_needs_reauth(db: AsyncSession, connection: CalendarConnection, reason: str) -> None:
    connection.status = "needs_reauth"
    connection.last_error = reason
    await db.commit()
