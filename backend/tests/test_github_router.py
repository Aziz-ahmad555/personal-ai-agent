"""The GitHub connection through the API, and the integrations overview."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.models import AuditLog
from app.db.models import User
from app.github import oauth
from app.github import router as router_module
from app.github.models import GithubConnection
from app.gmail.crypto import decrypt_token
from app.main import app

OWNER = "profile-owner@example.com"
TOKENS = oauth.TokenResponse(
    "ghu_access-token",
    "ghr_refresh-token",
    datetime.now(UTC) + timedelta(hours=8),
    datetime.now(UTC) + timedelta(days=180),
)


async def _user_id(session_factory: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    async with session_factory() as db:
        return (await db.execute(select(User).where(User.email == OWNER))).scalar_one().id


def _state(user_id: uuid.UUID) -> str:
    return oauth.build_authorization_url(user_id).split("state=")[1].split("&")[0]


def _fake_github(
    monkeypatch: pytest.MonkeyPatch,
    *,
    login: str = "aziz-ahmad555",
    installations: list[dict] | None = None,
) -> list[str]:
    """Stub the network. Returns the list that records which tokens got revoked."""
    revoked: list[str] = []

    async def exchange(code: str) -> oauth.TokenResponse:
        return TOKENS

    async def user(client: object, token: str) -> dict:
        return {"login": login, "id": 4242}

    async def installs(client: object, token: str) -> list[dict]:
        return installations or []

    async def revoke(token: str) -> bool:
        revoked.append(token)
        return True

    monkeypatch.setattr(oauth, "exchange_code_for_tokens", exchange)
    monkeypatch.setattr(router_module, "get_authenticated_user", user)
    monkeypatch.setattr(router_module, "list_installations", installs)
    monkeypatch.setattr(oauth, "revoke_token", revoke)
    return revoked


async def _callback(client: AsyncClient, user_id: uuid.UUID):
    return await client.get(
        "/github/oauth/callback",
        params={"code": "the-code", "state": _state(user_id)},
        follow_redirects=False,
    )


async def _audit_actions(session_factory: async_sessionmaker[AsyncSession]) -> list[str]:
    async with session_factory() as db:
        return list((await db.execute(select(AuditLog.action))).scalars().all())


# --- start and connection -------------------------------------------------------------------


async def test_start_requires_auth_and_returns_a_github_url(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    assert (await client.get("/github/oauth/start")).status_code == 401

    response = await client.get("/github/oauth/start", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["authorization_url"].startswith("https://github.com/login/oauth/authorize")


async def test_there_is_no_connection_before_connecting(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    assert (await client.get("/github/connection", headers=auth_headers)).status_code == 404
    assert (await client.get("/github/connection")).status_code == 401


# --- callback -------------------------------------------------------------------------------


async def test_a_successful_callback_connects_stores_encrypted_tokens_and_audits(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = await _user_id(session_factory)
    _fake_github(monkeypatch)

    response = await _callback(client, user_id)

    assert response.status_code in (302, 307)
    assert "connected=1" in response.headers["location"]
    async with session_factory() as db:
        stored = (await db.execute(select(GithubConnection))).scalar_one()
    assert stored.access_token_encrypted != "ghu_access-token"  # never plaintext at rest
    assert "ghu_access" not in (stored.access_token_encrypted or "")
    assert decrypt_token(stored.access_token_encrypted) == "ghu_access-token"  # type: ignore[arg-type]
    assert decrypt_token(stored.refresh_token_encrypted) == "ghr_refresh-token"  # type: ignore[arg-type]
    assert (stored.github_login, stored.github_user_id, stored.status) == (
        "aziz-ahmad555",
        4242,
        "connected",
    )
    async with session_factory() as db:
        entry = (
            await db.execute(select(AuditLog).where(AuditLog.action == "github.connected"))
        ).scalar_one()
    assert entry.risk_level == "green"
    assert entry.evidence["write_permissions"] == []
    assert "ghu_access" not in str(entry.evidence) + str(entry.summary)  # no token in the audit

    connection = await client.get("/github/connection", headers=auth_headers)
    assert connection.status_code == 200
    body = connection.json()
    assert body["github_login"] == "aziz-ahmad555"
    assert not {"access_token_encrypted", "refresh_token_encrypted"} & set(body)
    assert "ghu_" not in connection.text


async def test_an_app_with_write_permissions_is_refused_and_its_token_revoked(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    auth_headers: dict[str, str],
) -> None:
    user_id = await _user_id(session_factory)
    revoked = _fake_github(
        monkeypatch,
        installations=[
            {"id": 1, "account": "aziz-ahmad555", "permissions": {"contents": "write"}}
        ],
    )

    response = await _callback(client, user_id)

    assert "error=" in response.headers["location"]
    assert "contents%3Awrite" in response.headers["location"]
    assert revoked == ["ghu_access-token"]
    assert (await client.get("/github/connection", headers=auth_headers)).status_code == 404
    assert "github.connect_failed" in await _audit_actions(session_factory)


async def test_read_only_installations_are_recorded(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = await _user_id(session_factory)
    installations = [
        {"id": 1, "account": "aziz-ahmad555", "permissions": {"metadata": "read"}}
    ]
    _fake_github(monkeypatch, installations=installations)

    await _callback(client, user_id)

    body = (await client.get("/github/connection", headers=auth_headers)).json()
    assert body["installations"] == installations


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"error": "access_denied"}, "error=access_denied"),
        ({"code": "only-a-code"}, "error=missing_code_or_state"),
        ({"code": "c", "state": "not-a-real-state"}, "error="),
    ],
)
async def test_bad_callbacks_redirect_with_an_error_and_store_nothing(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    params: dict[str, str],
    expected: str,
) -> None:
    response = await client.get("/github/oauth/callback", params=params, follow_redirects=False)

    assert response.status_code in (302, 307)
    assert expected in response.headers["location"]
    async with session_factory() as db:
        assert (await db.execute(select(GithubConnection))).first() is None


async def test_a_rejected_code_is_reported_and_audited(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def rejected(code: str) -> oauth.TokenResponse:
        raise oauth.OAuthError("GitHub rejected the authorization code (bad_verification_code).")

    monkeypatch.setattr(oauth, "exchange_code_for_tokens", rejected)
    user_id = await _user_id(session_factory)

    response = await _callback(client, user_id)

    assert "bad_verification_code" in response.headers["location"]
    async with session_factory() as db:
        entry = (
            await db.execute(select(AuditLog).where(AuditLog.action == "github.connect_failed"))
        ).scalar_one()
    assert entry.status == "failed"
    assert "bad_verification_code" in (entry.error or "")


async def test_reconnecting_updates_the_same_row_and_records_an_account_change(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = await _user_id(session_factory)
    _fake_github(monkeypatch, login="first-account")
    await _callback(client, user_id)
    _fake_github(monkeypatch, login="second-account")

    await _callback(client, user_id)

    async with session_factory() as db:
        rows = (await db.execute(select(GithubConnection))).scalars().all()
        connected = (
            await db.execute(select(AuditLog).where(AuditLog.action == "github.connected"))
        ).scalars().all()
    assert [row.github_login for row in rows] == ["second-account"]
    assert [entry.evidence["previous_login"] for entry in connected] == [None, "first-account"]


# --- disconnect -----------------------------------------------------------------------------


async def test_disconnect_revokes_clears_tokens_and_audits(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = await _user_id(session_factory)
    revoked = _fake_github(monkeypatch)
    await _callback(client, user_id)

    response = await client.delete("/github/connection", headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["revoked_at_github"] is True
    assert body["connection"]["status"] == "disconnected"
    assert revoked == ["ghu_access-token"]
    async with session_factory() as db:
        stored = (await db.execute(select(GithubConnection))).scalar_one()
    assert stored.access_token_encrypted is None
    assert stored.refresh_token_encrypted is None
    assert "github.disconnected" in await _audit_actions(session_factory)


async def test_disconnect_still_works_when_github_cannot_revoke(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = await _user_id(session_factory)
    _fake_github(monkeypatch)
    await _callback(client, user_id)

    async def unreachable(token: str) -> bool:
        return False

    monkeypatch.setattr(oauth, "revoke_token", unreachable)

    response = await client.delete("/github/connection", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["revoked_at_github"] is False
    assert response.json()["connection"]["status"] == "disconnected"


async def test_disconnect_without_a_connection_is_404_and_needs_auth(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    assert (await client.delete("/github/connection", headers=auth_headers)).status_code == 404
    assert (await client.delete("/github/connection")).status_code == 401


# --- integrations overview ------------------------------------------------------------------


async def test_the_overview_lists_github_and_gmail_with_their_real_status(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = {i["key"]: i for i in (await client.get("/integrations", headers=auth_headers)).json()}
    assert before["github"]["status"] == "not_connected"
    assert before["github"]["path"] == "/github"
    assert before["gmail"]["status"] == "not_connected"

    _fake_github(monkeypatch)
    await _callback(client, await _user_id(session_factory))

    after = {i["key"]: i for i in (await client.get("/integrations", headers=auth_headers)).json()}
    assert after["github"]["status"] == "connected"


async def test_linkedin_indeed_and_fiverr_are_explicitly_unavailable(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    listing = await client.get("/integrations", headers=auth_headers)
    entries = {i["key"]: i for i in listing.json()}

    for key in ("linkedin", "indeed", "fiverr"):
        entry = entries[key]
        assert entry["status"] == "unavailable"
        assert entry["path"] is None  # nothing to open or connect
        assert "No authorized API access" in entry["reason"]
        assert "isn't an authorized channel" in entry["reason"]


async def test_the_overview_requires_auth(client: AsyncClient) -> None:
    assert (await client.get("/integrations")).status_code == 401


def test_no_route_exists_for_the_unavailable_platforms() -> None:
    paths = [getattr(route, "path", "") for route in app.routes]

    for platform in ("linkedin", "indeed", "fiverr"):
        assert not [path for path in paths if platform in path.lower()]
