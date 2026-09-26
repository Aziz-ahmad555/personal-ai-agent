import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import User
from app.gmail import oauth
from app.gmail import router as router_module
from app.gmail.crypto import encrypt_token
from app.gmail.models import EmailMessage, GmailConnection
from app.gmail.oauth import TokenResponse, build_authorization_url


def _fake_revoke(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Stub the network. Returns the list that records which tokens got revoked."""
    revoked: list[str] = []

    async def revoke(token: str) -> bool:
        revoked.append(token)
        return True

    monkeypatch.setattr(oauth, "revoke_token", revoke)
    return revoked


async def _get_user_id(session_factory: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    async with session_factory() as db:
        result = await db.execute(select(User).where(User.email == "profile-owner@example.com"))
        return result.scalar_one().id


async def _insert_connection(
    session_factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID, **overrides: object
) -> GmailConnection:
    async with session_factory() as db:
        fields: dict[str, object] = {
            "user_id": user_id,
            "google_email": "aziz@gmail.com",
            "access_token_encrypted": encrypt_token("access"),
            "refresh_token_encrypted": encrypt_token("refresh"),
            "token_expires_at": datetime.now(UTC) + timedelta(hours=1),
            "granted_scopes": "https://www.googleapis.com/auth/gmail.readonly",
            "status": "connected",
            **overrides,
        }
        connection = GmailConnection(**fields)  # type: ignore[arg-type]
        db.add(connection)
        await db.commit()
        await db.refresh(connection)
        return connection


async def test_oauth_start_requires_auth(client: AsyncClient) -> None:
    response = await client.get("/gmail/oauth/start")
    assert response.status_code == 401


async def test_oauth_start_returns_authorization_url(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.get("/gmail/oauth/start", headers=auth_headers)
    assert response.status_code == 200
    assert "accounts.google.com" in response.json()["authorization_url"]


async def test_connection_not_found_before_connecting(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.get("/gmail/connection", headers=auth_headers)
    assert response.status_code == 404


async def test_oauth_callback_creates_connection(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = await _get_user_id(session_factory)
    state = build_authorization_url(user_id).split("state=")[1].split("&")[0]

    async def fake_exchange(code: str) -> TokenResponse:
        return TokenResponse(
            access_token="fake-access",
            refresh_token="fake-refresh",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            granted_scopes="https://www.googleapis.com/auth/gmail.readonly",
        )

    async def fake_get_profile(client_obj: object, access_token: str) -> dict[str, str]:
        return {"emailAddress": "aziz@gmail.com", "historyId": "1"}

    monkeypatch.setattr(router_module, "exchange_code_for_tokens", fake_exchange)
    monkeypatch.setattr(router_module, "get_profile", fake_get_profile)

    response = await client.get(
        "/gmail/oauth/callback",
        params={"code": "auth-code", "state": state},
        follow_redirects=False,
    )

    assert response.status_code in (302, 307)
    assert "connected=1" in response.headers["location"]

    connection_response = await client.get("/gmail/connection", headers=auth_headers)
    assert connection_response.status_code == 200
    assert connection_response.json()["google_email"] == "aziz@gmail.com"
    assert connection_response.json()["status"] == "connected"


async def test_oauth_callback_redirects_with_error_on_denied_consent(client: AsyncClient) -> None:
    response = await client.get(
        "/gmail/oauth/callback", params={"error": "access_denied"}, follow_redirects=False
    )
    assert response.status_code in (302, 307)
    assert "error=access_denied" in response.headers["location"]


async def test_oauth_callback_rejects_invalid_state(client: AsyncClient) -> None:
    response = await client.get(
        "/gmail/oauth/callback",
        params={"code": "auth-code", "state": "not-a-real-state"},
        follow_redirects=False,
    )
    assert response.status_code in (302, 307)
    assert "error=" in response.headers["location"]


async def test_sync_requires_a_connection(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.post("/gmail/sync", headers=auth_headers)
    assert response.status_code == 404


async def test_sync_rejects_when_needs_reauth(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    user_id = await _get_user_id(session_factory)
    await _insert_connection(session_factory, user_id, status="needs_reauth")

    response = await client.post("/gmail/sync", headers=auth_headers)
    assert response.status_code == 409


async def test_messages_lists_stored_messages(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    user_id = await _get_user_id(session_factory)
    connection = await _insert_connection(session_factory, user_id)

    async with session_factory() as db:
        db.add(
            EmailMessage(
                connection_id=connection.id,
                gmail_message_id="m1",
                thread_id="t1",
                subject="Hello",
                snippet="Hi there",
                to_addresses=["aziz@example.com"],
                label_ids=["INBOX"],
                date=datetime.now(UTC),
            )
        )
        await db.commit()

    response = await client.get("/gmail/messages", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["subject"] == "Hello"
    assert "body_text" not in body[0]  # list view omits the full body


async def test_disconnect_purges_data_when_requested(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    revoked = _fake_revoke(monkeypatch)
    user_id = await _get_user_id(session_factory)
    connection = await _insert_connection(session_factory, user_id)
    async with session_factory() as db:
        db.add(
            EmailMessage(
                connection_id=connection.id,
                gmail_message_id="m1",
                thread_id="t1",
                snippet="",
                to_addresses=[],
                label_ids=[],
            )
        )
        await db.commit()

    response = await client.request(
        "DELETE", "/gmail/connection", headers=auth_headers, json={"purge_data": True}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "disconnected"
    assert revoked == ["refresh"]  # the refresh token is revoked over the access token

    async with session_factory() as db:
        rows = await db.execute(
            select(EmailMessage).where(EmailMessage.connection_id == connection.id)
        )
        remaining = rows.scalars().all()
        assert remaining == []


async def test_disconnect_keeps_data_when_not_requested(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_revoke(monkeypatch)
    user_id = await _get_user_id(session_factory)
    connection = await _insert_connection(session_factory, user_id)
    async with session_factory() as db:
        db.add(
            EmailMessage(
                connection_id=connection.id,
                gmail_message_id="m1",
                thread_id="t1",
                snippet="",
                to_addresses=[],
                label_ids=[],
            )
        )
        await db.commit()

    response = await client.request(
        "DELETE", "/gmail/connection", headers=auth_headers, json={"purge_data": False}
    )
    assert response.status_code == 200

    async with session_factory() as db:
        rows = await db.execute(
            select(EmailMessage).where(EmailMessage.connection_id == connection.id)
        )
        remaining = rows.scalars().all()
        assert len(remaining) == 1
