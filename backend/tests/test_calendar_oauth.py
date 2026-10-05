"""The Google Calendar OAuth handshake, the read-only client, and the token lifecycle. All
Calendar HTTP is mocked with httpx.MockTransport: no test reaches the real API."""

import inspect
import types
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import httpx
import jwt
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.security import create_token
from app.calendar import client as calendar_client
from app.calendar import oauth, service
from app.calendar.models import CalendarConnection
from app.db.models import User
from app.gmail.crypto import decrypt_token, encrypt_token

REAL_CLIENT = httpx.AsyncClient


def _mock_http(monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx.Request], httpx.Response]):
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        oauth.httpx, "AsyncClient", lambda **kwargs: REAL_CLIENT(transport=transport)
    )


def _json(data: object, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=data)


# --- authorization URL and state ------------------------------------------------------------


def test_the_authorization_url_asks_for_the_narrow_readonly_scope() -> None:
    url = oauth.build_authorization_url(uuid.uuid4())

    assert url.startswith(oauth.GOOGLE_AUTH_URL)
    assert "client_id=test-client-id.apps.googleusercontent.com" in url
    assert "redirect_uri=" in url
    assert "state=" in url
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert "calendar.events.readonly" in url
    assert "calendar.readonly" not in url  # the narrower scope only, not the broader one


def test_the_url_cannot_be_built_without_a_client_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(oauth, "get_settings", lambda: types.SimpleNamespace(google_client_id=None))

    with pytest.raises(oauth.OAuthError):
        oauth.build_authorization_url(uuid.uuid4())


def test_state_round_trips_the_user_id() -> None:
    user_id = uuid.uuid4()
    state = oauth.build_authorization_url(user_id).split("state=")[1].split("&")[0]

    assert oauth.verify_state(state) == user_id


def test_state_rejects_garbage_a_gmail_state_a_github_state_and_an_expired_one() -> None:
    with pytest.raises(oauth.OAuthError):
        oauth.verify_state("not-a-real-token")
    with pytest.raises(oauth.OAuthError):
        oauth.verify_state(create_token(uuid.uuid4(), token_type="oauth_state"))  # Gmail's kind
    with pytest.raises(oauth.OAuthError):
        oauth.verify_state(create_token(uuid.uuid4(), token_type="github_oauth_state"))
    with pytest.raises(oauth.OAuthError):
        oauth.verify_state(create_token(uuid.uuid4(), token_type="access"))

    from app.config import get_settings

    settings = get_settings()
    expired = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "type": "calendar_oauth_state",
            "iat": datetime.now(UTC) - timedelta(minutes=20),
            "exp": datetime.now(UTC) - timedelta(minutes=10),
        },
        settings.app_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(oauth.OAuthError):
        oauth.verify_state(expired)


# --- token exchange -------------------------------------------------------------------------


async def test_exchange_returns_tokens_and_checks_the_granted_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content.decode()
        return _json(
            {
                "access_token": "ya29.access",
                "refresh_token": "1//refresh",
                "expires_in": 3600,
                "scope": "https://www.googleapis.com/auth/calendar.events.readonly",
                "token_type": "Bearer",
            }
        )

    _mock_http(monkeypatch, handler)

    tokens = await oauth.exchange_code_for_tokens("the-code")

    assert "code=the-code" in str(seen["body"])
    assert tokens.access_token == "ya29.access"
    assert tokens.refresh_token == "1//refresh"
    assert tokens.expires_at > datetime.now(UTC) + timedelta(minutes=59)


async def test_exchange_rejects_a_response_missing_the_expected_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_http(
        monkeypatch,
        lambda request: _json(
            {
                "access_token": "x",
                "refresh_token": "y",
                "expires_in": 3600,
                "scope": "https://www.googleapis.com/auth/calendar.readonly",  # the broader one
            }
        ),
    )

    with pytest.raises(oauth.OAuthError, match="did not grant"):
        await oauth.exchange_code_for_tokens("code")


async def test_exchange_rejects_a_response_missing_a_refresh_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_http(
        monkeypatch,
        lambda request: _json(
            {
                "access_token": "x",
                "expires_in": 3600,
                "scope": "https://www.googleapis.com/auth/calendar.events.readonly",
            }
        ),
    )

    with pytest.raises(oauth.OAuthError, match="did not return a refresh token"):
        await oauth.exchange_code_for_tokens("code")


async def test_a_rejected_code_is_an_oauth_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_http(monkeypatch, lambda request: httpx.Response(400, json={"error": "invalid_grant"}))

    with pytest.raises(oauth.OAuthError):
        await oauth.exchange_code_for_tokens("stale-code")


# --- refresh --------------------------------------------------------------------------------


async def test_refresh_returns_a_new_access_token_and_no_refresh_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content.decode()
        return _json({"access_token": "ya29.new", "expires_in": 3600, "scope": "x"})

    _mock_http(monkeypatch, handler)

    tokens = await oauth.refresh_access_token("1//old-refresh")

    assert "grant_type=refresh_token" in seen["body"]
    assert "refresh_token=1%2F%2Fold-refresh" in seen["body"]
    assert tokens.access_token == "ya29.new"
    assert tokens.refresh_token is None  # Google doesn't reissue one on refresh


async def test_a_dead_refresh_token_asks_for_reauthentication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_http(monkeypatch, lambda request: _json({"error": "invalid_grant"}, status=400))

    with pytest.raises(oauth.ReauthRequiredError):
        await oauth.refresh_access_token("dead")


async def test_other_refresh_errors_are_not_mistaken_for_reauth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_http(monkeypatch, lambda request: httpx.Response(500))

    with pytest.raises(oauth.OAuthError) as caught:
        await oauth.refresh_access_token("token")
    assert not isinstance(caught.value, oauth.ReauthRequiredError)


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


# --- the read-only client ---------------------------------------------------------------------


def _api(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return REAL_CLIENT(transport=httpx.MockTransport(handler))


async def test_get_primary_calendar_sends_a_bearer_token_and_returns_the_account() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["auth"] = request.headers["authorization"]
        return _json({"id": "person-01@example.com", "summary": "person-01@example.com"})

    async with _api(handler) as http:
        calendar = await calendar_client.get_primary_calendar(http, "ya29.access")

    assert calendar["id"] == "person-01@example.com"
    assert seen == {
        "method": "GET",
        "path": "/calendar/v3/calendars/primary",
        "auth": "Bearer ya29.access",
    }


async def test_a_401_becomes_an_auth_error_and_other_failures_a_generic_one() -> None:
    async with _api(lambda request: httpx.Response(401)) as http:
        with pytest.raises(calendar_client.CalendarAuthError):
            await calendar_client.get_primary_calendar(http, "bad")
    async with _api(lambda request: httpx.Response(503)) as http:
        with pytest.raises(calendar_client.CalendarApiError) as caught:
            await calendar_client.get_primary_calendar(http, "token")
        assert not isinstance(caught.value, calendar_client.CalendarAuthError)


def test_the_client_module_can_only_read() -> None:
    source = inspect.getsource(calendar_client)
    writes = (".post(", ".put(", ".patch(", ".delete(", '"POST"', '"PUT"', '"PATCH"', '"DELETE"')
    for verb in writes:
        assert verb not in source


# --- token lifecycle ------------------------------------------------------------------------


async def _connection(
    session_factory: async_sessionmaker[AsyncSession], **overrides: object
) -> uuid.UUID:
    async with session_factory() as db:
        user = (await db.execute(select(User))).scalars().first()
        if user is None:
            user = User(email="owner@example.com", hashed_password="x")
            db.add(user)
            await db.flush()
        fields: dict[str, object] = {
            "user_id": user.id,
            "google_email": "person-01@example.com",
            "access_token_encrypted": encrypt_token("access-1"),
            "refresh_token_encrypted": encrypt_token("refresh-1"),
            "token_expires_at": datetime.now(UTC) + timedelta(hours=1),
            "granted_scopes": oauth.CALENDAR_READONLY_SCOPE,
            "status": "connected",
            **overrides,
        }
        connection = CalendarConnection(**fields)  # type: ignore[arg-type]
        db.add(connection)
        await db.commit()
        return connection.id


async def test_a_fresh_token_is_returned_without_calling_google(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def boom(token: str) -> oauth.TokenResponse:
        raise AssertionError("must not refresh")

    monkeypatch.setattr(oauth, "refresh_access_token", boom)
    connection_id = await _connection(session_factory)

    async with session_factory() as db:
        connection = await db.get(CalendarConnection, connection_id)
        assert await service.get_valid_access_token(db, connection) == "access-1"  # type: ignore[arg-type]


async def test_an_expiring_token_is_refreshed_and_stored(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    received: list[str] = []

    async def fake_refresh(refresh_token: str) -> oauth.TokenResponse:
        received.append(refresh_token)
        return oauth.TokenResponse("access-2", None, datetime.now(UTC) + timedelta(hours=1), "x")

    monkeypatch.setattr(oauth, "refresh_access_token", fake_refresh)
    connection_id = await _connection(
        session_factory, token_expires_at=datetime.now(UTC) + timedelta(seconds=20)
    )

    async with session_factory() as db:
        connection = await db.get(CalendarConnection, connection_id)
        token = await service.get_valid_access_token(db, connection)  # type: ignore[arg-type]

    assert (token, received) == ("access-2", ["refresh-1"])
    async with session_factory() as db:
        stored = await db.get(CalendarConnection, connection_id)
        assert decrypt_token(stored.access_token_encrypted) == "access-2"  # type: ignore[union-attr,arg-type]
        # The refresh token is untouched — Google didn't reissue one.
        assert decrypt_token(stored.refresh_token_encrypted) == "refresh-1"  # type: ignore[union-attr,arg-type]


async def test_a_refused_refresh_marks_the_connection_needs_reauth(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def dead(refresh_token: str) -> oauth.TokenResponse:
        raise oauth.ReauthRequiredError("Calendar access has expired or been revoked.")

    monkeypatch.setattr(oauth, "refresh_access_token", dead)
    connection_id = await _connection(
        session_factory, token_expires_at=datetime.now(UTC) - timedelta(hours=1)
    )

    async with session_factory() as db:
        connection = await db.get(CalendarConnection, connection_id)
        with pytest.raises(service.NotConnectedError):
            await service.get_valid_access_token(db, connection)  # type: ignore[arg-type]

    async with session_factory() as db:
        stored = await db.get(CalendarConnection, connection_id)
        assert stored.status == "needs_reauth"  # type: ignore[union-attr]
        assert "revoked" in (stored.last_error or "")  # type: ignore[union-attr]


async def test_an_expired_token_with_no_refresh_token_needs_reauth(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    connection_id = await _connection(
        session_factory,
        refresh_token_encrypted=None,
        token_expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )

    async with session_factory() as db:
        connection = await db.get(CalendarConnection, connection_id)
        with pytest.raises(service.NotConnectedError):
            await service.get_valid_access_token(db, connection)  # type: ignore[arg-type]
        assert connection.status == "needs_reauth"  # type: ignore[union-attr]


async def test_a_disconnected_connection_has_no_usable_token(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    connection_id = await _connection(
        session_factory, status="disconnected", access_token_encrypted=None
    )

    async with session_factory() as db:
        connection = await db.get(CalendarConnection, connection_id)
        with pytest.raises(service.NotConnectedError):
            await service.get_valid_access_token(db, connection)  # type: ignore[arg-type]
