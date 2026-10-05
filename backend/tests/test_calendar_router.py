"""The Calendar connection through the API, and its entry on the integrations overview."""

import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import unquote_plus

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.models import AuditLog
from app.auth.security import hash_password
from app.calendar import oauth
from app.calendar import router as router_module
from app.calendar.models import CalendarConnection
from app.db.models import User
from app.gmail.crypto import decrypt_token

OWNER = "profile-owner@example.com"
TOKENS = oauth.TokenResponse(
    "ya29.access-token",
    "1//refresh-token",
    datetime.now(UTC) + timedelta(hours=1),
    oauth.CALENDAR_READONLY_SCOPE,
)


async def _user_id(
    session_factory: async_sessionmaker[AsyncSession], email: str = OWNER
) -> uuid.UUID:
    async with session_factory() as db:
        return (await db.execute(select(User).where(User.email == email))).scalar_one().id


def _state(user_id: uuid.UUID) -> str:
    return oauth.build_authorization_url(user_id).split("state=")[1].split("&")[0]


def _fake_google(
    monkeypatch: pytest.MonkeyPatch, *, email: str = "person-01@example.com"
) -> list[str]:
    """Stub the network. Returns the list that records which tokens got revoked."""
    revoked: list[str] = []

    async def exchange(code: str) -> oauth.TokenResponse:
        return TOKENS

    async def primary(client: object, token: str) -> dict:
        return {"id": email, "summary": email}

    async def revoke(token: str) -> bool:
        revoked.append(token)
        return True

    monkeypatch.setattr(oauth, "exchange_code_for_tokens", exchange)
    monkeypatch.setattr(router_module, "get_primary_calendar", primary)
    monkeypatch.setattr(oauth, "revoke_token", revoke)
    return revoked


async def _callback(client: AsyncClient, user_id: uuid.UUID):
    return await client.get(
        "/calendar/oauth/callback",
        params={"code": "the-code", "state": _state(user_id)},
        follow_redirects=False,
    )


async def _audit_actions(session_factory: async_sessionmaker[AsyncSession]) -> list[str]:
    async with session_factory() as db:
        return list((await db.execute(select(AuditLog.action))).scalars().all())


# --- start and connection -------------------------------------------------------------------


async def test_start_requires_auth_and_returns_a_google_url(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    assert (await client.get("/calendar/oauth/start")).status_code == 401

    response = await client.get("/calendar/oauth/start", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["authorization_url"].startswith(
        "https://accounts.google.com/o/oauth2/v2/auth"
    )


async def test_there_is_no_connection_before_connecting(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    assert (await client.get("/calendar/connection", headers=auth_headers)).status_code == 404
    assert (await client.get("/calendar/connection")).status_code == 401


# --- callback -------------------------------------------------------------------------------


async def test_a_successful_callback_connects_stores_encrypted_tokens_and_audits(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = await _user_id(session_factory)
    _fake_google(monkeypatch)

    response = await _callback(client, user_id)

    assert response.status_code in (302, 307)
    assert "connected=1" in response.headers["location"]
    async with session_factory() as db:
        stored = (await db.execute(select(CalendarConnection))).scalar_one()
    assert stored.access_token_encrypted != "ya29.access-token"  # never plaintext at rest
    assert "ya29.access-token" not in (stored.access_token_encrypted or "")
    assert decrypt_token(stored.access_token_encrypted) == "ya29.access-token"  # type: ignore[arg-type]
    assert decrypt_token(stored.refresh_token_encrypted) == "1//refresh-token"  # type: ignore[arg-type]
    assert (stored.google_email, stored.status) == ("person-01@example.com", "connected")

    async with session_factory() as db:
        entry = (
            await db.execute(select(AuditLog).where(AuditLog.action == "calendar.connected"))
        ).scalar_one()
    assert entry.risk_level == "green"
    assert entry.evidence["google_email"] == "person-01@example.com"
    assert "ya29" not in str(entry.evidence) + str(entry.summary)  # no token in the audit

    connection = await client.get("/calendar/connection", headers=auth_headers)
    assert connection.status_code == 200
    body = connection.json()
    assert body["google_email"] == "person-01@example.com"
    assert not {"access_token_encrypted", "refresh_token_encrypted"} & set(body)
    assert "ya29" not in connection.text


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
    response = await client.get("/calendar/oauth/callback", params=params, follow_redirects=False)

    assert response.status_code in (302, 307)
    assert expected in response.headers["location"]
    async with session_factory() as db:
        assert (await db.execute(select(CalendarConnection))).first() is None


async def test_a_rejected_code_is_reported_and_audited(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def rejected(code: str) -> oauth.TokenResponse:
        raise oauth.OAuthError("Google rejected the authorization code.")

    monkeypatch.setattr(oauth, "exchange_code_for_tokens", rejected)
    user_id = await _user_id(session_factory)

    response = await _callback(client, user_id)

    assert "rejected" in unquote_plus(response.headers["location"])
    async with session_factory() as db:
        entry = (
            await db.execute(select(AuditLog).where(AuditLog.action == "calendar.connect_failed"))
        ).scalar_one()
    assert entry.status == "failed"
    assert "rejected the authorization code" in (entry.error or "")


async def test_reconnecting_updates_the_same_row_and_records_the_account_change(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = await _user_id(session_factory)
    _fake_google(monkeypatch, email="person-05@example.com")
    await _callback(client, user_id)
    _fake_google(monkeypatch, email="person-06@example.com")

    await _callback(client, user_id)

    async with session_factory() as db:
        rows = (await db.execute(select(CalendarConnection))).scalars().all()
        connected = (
            (await db.execute(select(AuditLog).where(AuditLog.action == "calendar.connected")))
            .scalars()
            .all()
        )
    assert [row.google_email for row in rows] == ["person-06@example.com"]
    assert [entry.evidence["previous_email"] for entry in connected] == [
        None,
        "person-05@example.com",
    ]


# --- disconnect -----------------------------------------------------------------------------


async def test_disconnect_revokes_clears_tokens_and_audits(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = await _user_id(session_factory)
    revoked = _fake_google(monkeypatch)
    await _callback(client, user_id)

    response = await client.delete("/calendar/connection", headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["revoked_at_google"] is True
    assert body["connection"]["status"] == "disconnected"
    assert revoked == ["ya29.access-token"]
    async with session_factory() as db:
        stored = (await db.execute(select(CalendarConnection))).scalar_one()
    assert stored.access_token_encrypted is None
    assert stored.refresh_token_encrypted is None
    assert "calendar.disconnected" in await _audit_actions(session_factory)


async def test_disconnect_still_works_when_google_cannot_revoke(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = await _user_id(session_factory)
    _fake_google(monkeypatch)
    await _callback(client, user_id)

    async def unreachable(token: str) -> bool:
        return False

    monkeypatch.setattr(oauth, "revoke_token", unreachable)

    response = await client.delete("/calendar/connection", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["revoked_at_google"] is False
    assert response.json()["connection"]["status"] == "disconnected"


async def test_disconnect_without_a_connection_is_404_and_needs_auth(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    assert (await client.delete("/calendar/connection", headers=auth_headers)).status_code == 404
    assert (await client.delete("/calendar/connection")).status_code == 401


# --- integrations overview ------------------------------------------------------------------


async def test_the_overview_lists_calendar_alongside_the_other_integrations(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = {i["key"]: i for i in (await client.get("/integrations", headers=auth_headers)).json()}
    assert before["calendar"]["status"] == "not_connected"
    assert before["calendar"]["path"] == "/calendar"

    _fake_google(monkeypatch)
    await _callback(client, await _user_id(session_factory))

    after = {i["key"]: i for i in (await client.get("/integrations", headers=auth_headers)).json()}
    assert after["calendar"]["status"] == "connected"


async def test_isolation_from_other_users(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with session_factory() as db:
        db.add(User(email="other@example.com", hashed_password=hash_password("x-y-z-123456")))
        await db.commit()
    other_id = await _user_id(session_factory, email="other@example.com")
    _fake_google(monkeypatch)
    await _callback(client, other_id)

    # The owner (auth_headers' user) still sees no connection of their own.
    assert (await client.get("/calendar/connection", headers=auth_headers)).status_code == 404
    assert (await client.delete("/calendar/connection", headers=auth_headers)).status_code == 404
