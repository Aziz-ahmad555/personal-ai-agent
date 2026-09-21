"""The OAuth authorization-code handshake with a GitHub App, over plain async REST calls (same
approach as the Gmail flow: no blocking SDK, and the CSRF `state` carries our own signed user
reference rather than a session cookie).

GitHub differs from Google in ways that matter here, so they're handled explicitly:
- Failures on the token endpoint come back as HTTP 200 with an `error` field, so the body is
  always checked, never just the status code.
- A GitHub App user token has no OAuth scopes. What it can do is decided by the app's
  registered permissions, which the callback verifies separately (see service.write_permissions).
- With expiring tokens on (the default for new apps) the access token lasts hours and the
  refresh token rotates on every use, so the new refresh token must be stored each time.
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

GITHUB_AUTH_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_API_URL = "https://api.github.com"


class OAuthError(RuntimeError):
    """The handshake failed: bad state, rejected code, or a response we can't trust."""


class ReauthRequiredError(OAuthError):
    """The stored refresh token no longer works (expired after ~6 months, revoked, or already
    used). The caller marks the connection needs_reauth and asks the user to reconnect."""


@dataclass(frozen=True)
class TokenResponse:
    access_token: str
    refresh_token: str | None
    # None when the app issues non-expiring tokens.
    expires_at: datetime | None
    refresh_expires_at: datetime | None


def _credentials() -> tuple[str, str]:
    settings = get_settings()
    if not settings.github_client_id or not settings.github_client_secret:
        raise OAuthError("GITHUB_CLIENT_ID/GITHUB_CLIENT_SECRET are not set.")
    return settings.github_client_id, settings.github_client_secret


def build_authorization_url(user_id: uuid.UUID) -> str:
    settings = get_settings()
    if not settings.github_client_id:
        raise OAuthError("GITHUB_CLIENT_ID is not set — cannot start the GitHub connection.")
    params = {
        "client_id": settings.github_client_id,
        "redirect_uri": settings.github_redirect_uri,
        "state": create_token(user_id, token_type="github_oauth_state"),
    }
    return f"{GITHUB_AUTH_URL}?{urlencode(params)}"


def verify_state(state: str) -> uuid.UUID:
    try:
        return decode_token(state, expected_type="github_oauth_state")
    except jwt.InvalidTokenError as exc:
        raise OAuthError("Invalid or expired state — please try connecting again.") from exc


def _parse_tokens(data: dict[str, object]) -> TokenResponse:
    access_token = data.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise OAuthError("GitHub did not return an access token.")
    now = datetime.now(UTC)
    expires_in = data.get("expires_in")
    refresh_expires_in = data.get("refresh_token_expires_in")
    refresh_token = data.get("refresh_token")
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token if isinstance(refresh_token, str) and refresh_token else None,
        expires_at=now + timedelta(seconds=int(expires_in))  # type: ignore[call-overload]
        if expires_in
        else None,
        refresh_expires_at=now + timedelta(seconds=int(refresh_expires_in))  # type: ignore[call-overload]
        if refresh_expires_in
        else None,
    )


async def _post_token(form: dict[str, str]) -> dict[str, object]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            GITHUB_TOKEN_URL, data=form, headers={"Accept": "application/json"}
        )
    if response.status_code != 200:
        logger.warning("github_oauth_token_http_error", status=response.status_code)
        raise OAuthError("GitHub's token endpoint returned an error.")
    try:
        data = response.json()
    except ValueError as exc:
        raise OAuthError("GitHub's token endpoint returned something unreadable.") from exc
    if not isinstance(data, dict):
        raise OAuthError("GitHub's token endpoint returned something unreadable.")
    return data


async def exchange_code_for_tokens(code: str) -> TokenResponse:
    client_id, client_secret = _credentials()
    data = await _post_token(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": get_settings().github_redirect_uri,
        }
    )
    if data.get("error"):
        logger.warning("github_oauth_code_rejected", error=data.get("error"))
        raise OAuthError(f"GitHub rejected the authorization code ({data['error']}).")
    return _parse_tokens(data)


async def refresh_access_token(refresh_token: str) -> TokenResponse:
    client_id, client_secret = _credentials()
    data = await _post_token(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
    )
    error = data.get("error")
    if error == "bad_refresh_token":
        raise ReauthRequiredError("GitHub access has expired or been revoked.")
    if error:
        logger.warning("github_oauth_refresh_failed", error=error)
        raise OAuthError("Failed to refresh the GitHub access token.")
    return _parse_tokens(data)


async def revoke_token(access_token: str) -> bool:
    """Ask GitHub to invalidate this one token. Best effort: returns whether GitHub confirmed.
    A failure never blocks a local disconnect, but the caller reports it honestly."""
    try:
        client_id, client_secret = _credentials()
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.request(
                "DELETE",
                f"{GITHUB_API_URL}/applications/{client_id}/token",
                auth=(client_id, client_secret),
                json={"access_token": access_token},
                headers={"Accept": "application/vnd.github+json"},
            )
        return response.status_code == 204
    except (OAuthError, httpx.HTTPError):
        return False
