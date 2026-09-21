"""The GitHub App handshake, the read-only client, and the token lifecycle. All GitHub HTTP is
mocked with httpx.MockTransport: no test reaches the real API."""

import json
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
from app.db.models import User
from app.github import client as github_client
from app.github import oauth, service
from app.github.models import GithubConnection
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


def test_the_authorization_url_asks_for_no_scopes() -> None:
    url = oauth.build_authorization_url(uuid.uuid4())

    assert url.startswith(oauth.GITHUB_AUTH_URL)
    assert "client_id=test-github-client-id" in url
    assert "redirect_uri=" in url
    assert "state=" in url
    assert "scope" not in url  # a GitHub App's power comes from its registered permissions


def test_the_url_cannot_be_built_without_a_client_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(oauth, "get_settings", lambda: types.SimpleNamespace(github_client_id=None))

    with pytest.raises(oauth.OAuthError):
        oauth.build_authorization_url(uuid.uuid4())


def test_state_round_trips_the_user_id() -> None:
    user_id = uuid.uuid4()
    state = oauth.build_authorization_url(user_id).split("state=")[1].split("&")[0]

    assert oauth.verify_state(state) == user_id


def test_state_rejects_garbage_a_gmail_state_and_an_expired_one() -> None:
    with pytest.raises(oauth.OAuthError):
        oauth.verify_state("not-a-real-token")
    with pytest.raises(oauth.OAuthError):
        oauth.verify_state(create_token(uuid.uuid4(), token_type="oauth_state"))  # Gmail's kind
    with pytest.raises(oauth.OAuthError):
        oauth.verify_state(create_token(uuid.uuid4(), token_type="access"))

    from app.config import get_settings

    settings = get_settings()
    expired = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "type": "github_oauth_state",
            "iat": datetime.now(UTC) - timedelta(minutes=20),
            "exp": datetime.now(UTC) - timedelta(minutes=10),
        },
        settings.app_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(oauth.OAuthError):
        oauth.verify_state(expired)


# --- token exchange -------------------------------------------------------------------------


async def test_exchange_returns_expiring_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["accept"] = request.headers["accept"]
        seen["body"] = request.content.decode()
        return _json(
            {
                "access_token": "ghu_access",
                "expires_in": 28800,
                "refresh_token": "ghr_refresh",
                "refresh_token_expires_in": 15811200,
                "token_type": "bearer",
                "scope": "",
            }
        )

    _mock_http(monkeypatch, handler)

    tokens = await oauth.exchange_code_for_tokens("the-code")

    assert seen["url"] == oauth.GITHUB_TOKEN_URL
    assert seen["accept"] == "application/json"
    assert "code=the-code" in str(seen["body"])
    assert tokens.access_token == "ghu_access"
    assert tokens.refresh_token == "ghr_refresh"
    assert tokens.expires_at is not None
    assert tokens.expires_at > datetime.now(UTC) + timedelta(hours=7)
    assert tokens.refresh_expires_at is not None


async def test_exchange_accepts_non_expiring_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_http(monkeypatch, lambda request: _json({"access_token": "ghu_forever"}))

    tokens = await oauth.exchange_code_for_tokens("code")

    assert tokens.refresh_token is None
    assert tokens.expires_at is None
    assert tokens.refresh_expires_at is None


async def test_an_error_inside_a_200_response_is_still_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # GitHub reports a bad code as HTTP 200 with an `error` field, not as an HTTP error.
    _mock_http(monkeypatch, lambda request: _json({"error": "bad_verification_code"}))

    with pytest.raises(oauth.OAuthError, match="bad_verification_code"):
        await oauth.exchange_code_for_tokens("stale")


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500, text="boom"),
        httpx.Response(200, text="not json"),
        httpx.Response(200, json=["a", "list"]),
        httpx.Response(200, json={"token_type": "bearer"}),  # no access_token
    ],
)
async def test_unusable_token_responses_are_rejected(
    monkeypatch: pytest.MonkeyPatch, response: httpx.Response
) -> None:
    _mock_http(monkeypatch, lambda request: response)

    with pytest.raises(oauth.OAuthError):
        await oauth.exchange_code_for_tokens("code")


async def test_refresh_returns_a_rotated_refresh_token(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content.decode()
        return _json(
            {
                "access_token": "ghu_new",
                "expires_in": 28800,
                "refresh_token": "ghr_new",
                "refresh_token_expires_in": 15811200,
            }
        )

    _mock_http(monkeypatch, handler)

    tokens = await oauth.refresh_access_token("ghr_old")

    assert "grant_type=refresh_token" in seen["body"]
    assert "refresh_token=ghr_old" in seen["body"]
    assert (tokens.access_token, tokens.refresh_token) == ("ghu_new", "ghr_new")


async def test_a_dead_refresh_token_asks_for_reauthentication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_http(monkeypatch, lambda request: _json({"error": "bad_refresh_token"}))

    with pytest.raises(oauth.ReauthRequiredError):
        await oauth.refresh_access_token("dead")


async def test_other_refresh_errors_are_not_mistaken_for_reauth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_http(monkeypatch, lambda request: _json({"error": "temporarily_unavailable"}))

    with pytest.raises(oauth.OAuthError) as caught:
        await oauth.refresh_access_token("token")
    assert not isinstance(caught.value, oauth.ReauthRequiredError)


async def test_revoking_reports_whether_github_confirmed(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers["authorization"].startswith("Basic ")
        return httpx.Response(204)

    _mock_http(monkeypatch, handler)

    assert await oauth.revoke_token("ghu_access") is True
    assert seen == {
        "method": "DELETE",
        "path": "/applications/test-github-client-id/token",
        "body": {"access_token": "ghu_access"},
        "auth": True,
    }

    _mock_http(monkeypatch, lambda request: httpx.Response(404))
    assert await oauth.revoke_token("ghu_access") is False


async def test_revoking_never_raises_when_github_is_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    _mock_http(monkeypatch, handler)

    assert await oauth.revoke_token("ghu_access") is False


# --- read-only client -----------------------------------------------------------------------


def _api(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return REAL_CLIENT(transport=httpx.MockTransport(handler))


async def test_the_user_call_sends_a_bearer_token_and_returns_the_account() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["auth"] = request.headers["authorization"]
        seen["version"] = request.headers["x-github-api-version"]
        return _json({"login": "aziz-ahmad555", "id": 123456789, "type": "User"})

    async with _api(handler) as http:
        user = await github_client.get_authenticated_user(http, "ghu_access")

    assert user["login"] == "aziz-ahmad555"
    assert seen == {
        "method": "GET",
        "path": "/user",
        "auth": "Bearer ghu_access",
        "version": "2022-11-28",
    }


async def test_a_401_becomes_an_auth_error_and_other_failures_a_generic_one() -> None:
    async with _api(lambda request: httpx.Response(401)) as http:
        with pytest.raises(github_client.GithubAuthError):
            await github_client.get_authenticated_user(http, "bad")
    async with _api(lambda request: httpx.Response(503)) as http:
        with pytest.raises(github_client.GithubApiError) as caught:
            await github_client.get_authenticated_user(http, "token")
        assert not isinstance(caught.value, github_client.GithubAuthError)
    async with _api(lambda request: _json({"unexpected": True})) as http:
        with pytest.raises(github_client.GithubApiError):
            await github_client.get_authenticated_user(http, "token")


async def test_installations_are_reduced_to_what_matters() -> None:
    payload = {
        "total_count": 1,
        "installations": [
            {
                "id": 9,
                "account": {"login": "aziz-ahmad555", "type": "User"},
                "repository_selection": "selected",
                "permissions": {"metadata": "read"},
                "access_tokens_url": "https://api.github.com/x",
            }
        ],
    }

    async with _api(lambda request: _json(payload)) as http:
        installations = await github_client.list_installations(http, "token")

    assert installations == [
        {
            "id": 9,
            "account": "aziz-ahmad555",
            "repository_selection": "selected",
            "permissions": {"metadata": "read"},
        }
    ]


def test_the_client_module_can_only_read() -> None:
    import inspect

    source = inspect.getsource(github_client)
    writes = (".post(", ".put(", ".patch(", ".delete(", '"POST"', '"PUT"', '"PATCH"', '"DELETE"')
    for verb in writes:
        assert verb not in source


# --- the read-only guard --------------------------------------------------------------------


def test_write_permissions_are_found_in_any_installation() -> None:
    installations = [
        {"permissions": {"metadata": "read", "contents": "read"}},
        {"permissions": {"contents": "write", "issues": "admin", "pull_requests": "read"}},
    ]

    assert service.write_permissions(installations) == ["contents:write", "issues:admin"]


def test_a_read_only_or_absent_installation_has_no_write_permissions() -> None:
    assert service.write_permissions([]) == []
    assert service.write_permissions([{"permissions": {"metadata": "read"}}]) == []
    assert service.write_permissions([{"permissions": None}, {}]) == []


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
            "github_login": "aziz-ahmad555",
            "github_user_id": 1,
            "access_token_encrypted": encrypt_token("access-1"),
            "refresh_token_encrypted": encrypt_token("refresh-1"),
            "token_expires_at": datetime.now(UTC) + timedelta(hours=4),
            "installations": [],
            "status": "connected",
            **overrides,
        }
        connection = GithubConnection(**fields)  # type: ignore[arg-type]
        db.add(connection)
        await db.commit()
        return connection.id


async def test_a_fresh_token_is_returned_without_calling_github(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def boom(token: str) -> oauth.TokenResponse:
        raise AssertionError("must not refresh")

    monkeypatch.setattr(oauth, "refresh_access_token", boom)
    connection_id = await _connection(session_factory)

    async with session_factory() as db:
        connection = await db.get(GithubConnection, connection_id)
        assert await service.get_valid_access_token(db, connection) == "access-1"  # type: ignore[arg-type]


async def test_an_expiring_token_is_refreshed_and_the_rotated_pair_is_stored(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    received: list[str] = []

    async def fake_refresh(refresh_token: str) -> oauth.TokenResponse:
        received.append(refresh_token)
        return oauth.TokenResponse(
            "access-2",
            "refresh-2",
            datetime.now(UTC) + timedelta(hours=8),
            datetime.now(UTC) + timedelta(days=180),
        )

    monkeypatch.setattr(oauth, "refresh_access_token", fake_refresh)
    connection_id = await _connection(
        session_factory, token_expires_at=datetime.now(UTC) + timedelta(seconds=20)
    )

    async with session_factory() as db:
        connection = await db.get(GithubConnection, connection_id)
        token = await service.get_valid_access_token(db, connection)  # type: ignore[arg-type]

    assert (token, received) == ("access-2", ["refresh-1"])
    async with session_factory() as db:
        stored = await db.get(GithubConnection, connection_id)
        assert decrypt_token(stored.access_token_encrypted) == "access-2"  # type: ignore[union-attr,arg-type]
        assert decrypt_token(stored.refresh_token_encrypted) == "refresh-2"  # type: ignore[union-attr,arg-type]


async def test_a_refused_refresh_marks_the_connection_needs_reauth(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def dead(refresh_token: str) -> oauth.TokenResponse:
        raise oauth.ReauthRequiredError("GitHub access has expired or been revoked.")

    monkeypatch.setattr(oauth, "refresh_access_token", dead)
    connection_id = await _connection(
        session_factory, token_expires_at=datetime.now(UTC) - timedelta(hours=1)
    )

    async with session_factory() as db:
        connection = await db.get(GithubConnection, connection_id)
        with pytest.raises(service.NotConnectedError):
            await service.get_valid_access_token(db, connection)  # type: ignore[arg-type]

    async with session_factory() as db:
        stored = await db.get(GithubConnection, connection_id)
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
        connection = await db.get(GithubConnection, connection_id)
        with pytest.raises(service.NotConnectedError):
            await service.get_valid_access_token(db, connection)  # type: ignore[arg-type]
        assert connection.status == "needs_reauth"  # type: ignore[union-attr]


async def test_a_non_expiring_token_is_always_used_as_is(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    connection_id = await _connection(
        session_factory, token_expires_at=None, refresh_token_encrypted=None
    )

    async with session_factory() as db:
        connection = await db.get(GithubConnection, connection_id)
        assert await service.get_valid_access_token(db, connection) == "access-1"  # type: ignore[arg-type]


async def test_a_disconnected_connection_has_no_usable_token(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    connection_id = await _connection(
        session_factory, status="disconnected", access_token_encrypted=None
    )

    async with session_factory() as db:
        connection = await db.get(GithubConnection, connection_id)
        with pytest.raises(service.NotConnectedError):
            await service.get_valid_access_token(db, connection)  # type: ignore[arg-type]
