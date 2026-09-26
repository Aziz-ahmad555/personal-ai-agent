import types
import uuid
from collections.abc import Callable

import httpx
import jwt
import pytest

from app.gmail import oauth

REAL_CLIENT = httpx.AsyncClient


def _mock_http(monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx.Request], httpx.Response]):
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        oauth.httpx, "AsyncClient", lambda **kwargs: REAL_CLIENT(transport=transport)
    )


def test_build_authorization_url_includes_required_params() -> None:
    user_id = uuid.uuid4()
    url = oauth.build_authorization_url(user_id)

    assert url.startswith(oauth.GOOGLE_AUTH_URL)
    assert "scope=" in url
    assert "gmail.readonly" in url
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert "state=" in url


def test_build_authorization_url_raises_without_client_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        oauth, "get_settings", lambda: types.SimpleNamespace(google_client_id=None)
    )
    with pytest.raises(oauth.OAuthError):
        oauth.build_authorization_url(uuid.uuid4())


def test_verify_state_round_trips_the_user_id() -> None:
    user_id = uuid.uuid4()
    state = oauth.build_authorization_url(user_id).split("state=")[1].split("&")[0]
    assert oauth.verify_state(state) == user_id


def test_verify_state_rejects_garbage() -> None:
    with pytest.raises(oauth.OAuthError):
        oauth.verify_state("not-a-real-token")


# --- revoke -----------------------------------------------------------------------------


async def test_revoke_reports_success(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200)

    _mock_http(monkeypatch, handler)

    assert await oauth.revoke_token("ya29.access") is True
    assert "token=ya29.access" in seen["url"]


async def test_revoke_never_raises_when_google_is_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    _mock_http(monkeypatch, handler)

    assert await oauth.revoke_token("ya29.access") is False


async def test_revoke_reports_failure_on_a_non_200(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_http(monkeypatch, lambda request: httpx.Response(400))

    assert await oauth.revoke_token("already-revoked") is False


def test_verify_state_rejects_a_token_of_the_wrong_type() -> None:
    from app.auth.security import create_token

    access_token = create_token(uuid.uuid4(), token_type="access")
    with pytest.raises(oauth.OAuthError):
        oauth.verify_state(access_token)


def test_verify_state_rejects_expired_state() -> None:
    import datetime as dt

    from app.config import get_settings

    settings = get_settings()
    payload = {
        "sub": str(uuid.uuid4()),
        "type": "oauth_state",
        "iat": dt.datetime.now(dt.UTC) - dt.timedelta(minutes=20),
        "exp": dt.datetime.now(dt.UTC) - dt.timedelta(minutes=10),
    }
    expired_state = jwt.encode(payload, settings.app_secret_key, algorithm=settings.jwt_algorithm)

    with pytest.raises(oauth.OAuthError):
        oauth.verify_state(expired_state)
