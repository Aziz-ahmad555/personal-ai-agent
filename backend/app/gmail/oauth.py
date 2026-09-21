"""The OAuth2 authorization-code handshake with Google, hand-rolled over plain REST calls
(not google-auth-oauthlib) — this keeps the whole flow async (no blocking SDK calls inside
FastAPI request handlers) and lets the CSRF `state` param carry our own signed user
reference, integrated with this app's existing JWT-based auth rather than a session cookie
this app doesn't otherwise use.

Every response from Google is treated as untrusted input: the granted scope is checked
against what we actually need (never assumed to match what was requested), and a missing
refresh_token or a revoked-grant refresh failure both get raised as distinct, specific
errors so the caller can react correctly instead of treating every failure the same way.
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
GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"


class OAuthError(RuntimeError):
    """The OAuth handshake itself failed — bad state, rejected code, missing refresh
    token, or Google granting a different scope than we asked for."""


class ReauthRequiredError(OAuthError):
    """The stored refresh token no longer works (revoked, or the 7-day cap that applies
    while the Google OAuth consent screen stays in "Testing" status). The caller must mark
    the connection needs_reauth and prompt the user to reconnect — this is expected,
    routine behavior for this app's setup, not a bug."""


@dataclass(frozen=True)
class TokenResponse:
    access_token: str
    refresh_token: str | None
    expires_at: datetime
    granted_scopes: str


def build_authorization_url(user_id: uuid.UUID) -> str:
    settings = get_settings()
    if not settings.google_client_id:
        raise OAuthError("GOOGLE_CLIENT_ID is not set — cannot start the Gmail OAuth flow.")

    state = create_token(user_id, token_type="oauth_state")
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": GMAIL_READONLY_SCOPE,
        "access_type": "offline",
        "prompt": "consent",  # forces a refresh_token even on re-consent
        "state": state,
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


def verify_state(state: str) -> uuid.UUID:
    try:
        return decode_token(state, expected_type="oauth_state")
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
                "redirect_uri": settings.google_redirect_uri,
                "grant_type": "authorization_code",
            },
        )

    if response.status_code != 200:
        logger.warning("gmail_oauth_token_exchange_failed", status=response.status_code)
        raise OAuthError("Google rejected the authorization code.")

    data = response.json()
    granted_scopes = data.get("scope", "")
    if GMAIL_READONLY_SCOPE not in granted_scopes:
        raise OAuthError(
            f"Google did not grant the expected gmail.readonly scope (got: {granted_scopes!r})."
        )
    refresh_token = data.get("refresh_token")
    if not refresh_token:
        raise OAuthError(
            "Google did not return a refresh token. This usually means an existing grant "
            "for this app is still active — remove Gmail access for this app at "
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
            raise ReauthRequiredError("Gmail access has expired or been revoked.")
        logger.warning("gmail_oauth_refresh_failed", status=response.status_code)
        raise OAuthError("Failed to refresh the Gmail access token.")

    data = response.json()
    return TokenResponse(
        access_token=data["access_token"],
        refresh_token=None,  # the refresh grant doesn't reissue one; the original stays valid
        expires_at=datetime.now(UTC) + timedelta(seconds=data["expires_in"]),
        granted_scopes=data.get("scope", ""),
    )
