"""The OAuth2 authorization-code handshake with Google for Calendar — same Google Cloud project
and OAuth client as Gmail (app/gmail/oauth.py), but its own connection, its own callback path and
its own narrow scope, so disconnecting one never touches the other and each integration keeps an
explicit CAN/CANNOT list of its own (see app/calendar/router.py's docstring).

Mirrors app/gmail/oauth.py's shape deliberately: a signed JWT `state` instead of a session
cookie, granted-scope verification (never assume Google gave what was asked), and a distinct
ReauthRequiredError so the caller can react to an expired grant differently from a hard failure.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx
import jwt

from app.auth.security import create_token, decode_token
from app.config import get_settings
from app.logging import get_logger

logger = get_logger(__name__)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
# Read-only, and narrower than calendar.readonly: this lets us read events on a calendar
# we already know the id of ("primary"), without also granting calendar-list or settings
# access we don't need.
CALENDAR_READONLY_SCOPE = "https://www.googleapis.com/auth/calendar.events.readonly"


class OAuthError(RuntimeError):
    """The OAuth handshake itself failed — bad state, rejected code, missing refresh
    token, or Google granting a different scope than we asked for."""


class ReauthRequiredError(OAuthError):
    """The stored refresh token no longer works (revoked, or the 7-day cap that applies
    while the Google OAuth consent screen stays in "Testing" status). The caller must mark
    the connection needs_reauth and prompt the user to reconnect — expected, routine
    behavior for this app's setup, not a bug."""


@dataclass(frozen=True)
class TokenResponse:
    access_token: str
    refresh_token: str | None
    expires_at: datetime
    granted_scopes: str


def build_authorization_url(user_id: uuid.UUID) -> str:
    settings = get_settings()
    if not settings.google_client_id:
        raise OAuthError("GOOGLE_CLIENT_ID is not set — cannot start the Calendar OAuth flow.")

    state = create_token(user_id, token_type="calendar_oauth_state")
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_calendar_redirect_uri,
        "response_type": "code",
        "scope": CALENDAR_READONLY_SCOPE,
        "access_type": "offline",
        "prompt": "consent",  # forces a refresh_token even on re-consent
        "state": state,
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


def verify_state(state: str) -> uuid.UUID:
    try:
        return decode_token(state, expected_type="calendar_oauth_state")
    except jwt.InvalidTokenError as exc:
        raise OAuthError("Invalid or expired OAuth state — please try connecting again.") from exc


def _require_credentials() -> tuple[str, str]:
    settings = get_settings()
    if not settings.google_client_id or not settings.google_client_secret:
        raise OAuthError("GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET are not set.")
    return settings.google_client_id, settings.google_client_secret


async def exchange_code_for_tokens(code: str) -> TokenResponse:
    client_id, client_secret = _require_credentials()
    settings = get_settings()

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": settings.google_calendar_redirect_uri,
                "grant_type": "authorization_code",
            },
        )

    if response.status_code != 200:
        logger.warning("calendar_oauth_token_exchange_failed", status=response.status_code)
        raise OAuthError("Google rejected the authorization code.")

    data = response.json()
    granted_scopes = data.get("scope", "")
    if CALENDAR_READONLY_SCOPE not in granted_scopes:
        raise OAuthError(
            f"Google did not grant the expected calendar.events.readonly scope "
            f"(got: {granted_scopes!r})."
        )
    refresh_token = data.get("refresh_token")
    if not refresh_token:
        raise OAuthError(
            "Google did not return a refresh token. This usually means an existing grant "
            "for this app is still active — remove Calendar access for this app at "
            "https://myaccount.google.com/permissions and try connecting again."
        )

    return TokenResponse(
        access_token=data["access_token"],
        refresh_token=refresh_token,
        expires_at=datetime.now(UTC) + timedelta(seconds=data["expires_in"]),
        granted_scopes=granted_scopes,
    )


async def refresh_access_token(refresh_token: str) -> TokenResponse:
    client_id, client_secret = _require_credentials()

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "refresh_token",
            },
        )

    if response.status_code != 200:
        error_code = None
        try:
            error_code = response.json().get("error")
        except ValueError:
            pass
        if error_code == "invalid_grant":
            raise ReauthRequiredError("Calendar access has expired or been revoked.")
        logger.warning("calendar_oauth_refresh_failed", status=response.status_code)
        raise OAuthError("Failed to refresh the Calendar access token.")

    data = response.json()
    return TokenResponse(
        access_token=data["access_token"],
        refresh_token=None,  # Google's refresh grant doesn't reissue one; the original stays valid
        expires_at=datetime.now(UTC) + timedelta(seconds=data["expires_in"]),
        granted_scopes=data.get("scope", ""),
    )


async def revoke_token(token: str) -> bool:
    """Best-effort: tells Google to invalidate this token so it can't be used again, even
    though it's about to be deleted from our own database either way. Returns whether Google
    confirmed it (never raises — an unreachable Google must not block disconnecting)."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(GOOGLE_REVOKE_URL, params={"token": token})
        return response.status_code == 200
    except httpx.HTTPError as exc:
        logger.warning("calendar_oauth_revoke_failed", error=str(exc))
        return False
