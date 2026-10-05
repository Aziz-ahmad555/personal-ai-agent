import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import User
from app.gmail import sync as sync_module
from app.gmail.client import GmailApiError, GmailMessage
from app.gmail.crypto import encrypt_token
from app.gmail.models import EmailMessage, GmailConnection, GmailSyncRun
from app.gmail.oauth import ReauthRequiredError


async def _make_connection(
    db: AsyncSession, *, expired: bool = False, last_history_id: str | None = None
) -> GmailConnection:
    user = User(email=f"gmail-test-{uuid.uuid4()}@example.com", hashed_password="x")
    db.add(user)
    await db.flush()
    expires_delta = timedelta(minutes=-5) if expired else timedelta(hours=1)
    connection = GmailConnection(
        user_id=user.id,
        google_email="person-01@example.com",
        access_token_encrypted=encrypt_token("fake-access-token"),
        refresh_token_encrypted=encrypt_token("fake-refresh-token"),
        token_expires_at=datetime.now(UTC) + expires_delta,
        granted_scopes="https://www.googleapis.com/auth/gmail.readonly",
        status="connected",
        last_history_id=last_history_id,
    )
    db.add(connection)
    await db.flush()
    return connection


def _fake_message(message_id: str) -> GmailMessage:
    return GmailMessage(
        gmail_message_id=message_id,
        thread_id=f"thread-{message_id}",
        subject=f"Subject {message_id}",
        from_address="sender@example.com",
        to_addresses=["aziz@example.com"],
        date=datetime.now(UTC),
        snippet="snippet",
        body_text="body",
        label_ids=["INBOX"],
    )


async def test_backfill_stores_new_messages_and_sets_history_cursor(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_list_message_ids(client, access_token, *, query=None, page_token=None):  # type: ignore[no-untyped-def]
        if page_token is None:
            return ["m1", "m2"], "page2"
        return ["m3"], None

    async def fake_get_message(client, access_token, message_id):  # type: ignore[no-untyped-def]
        return _fake_message(message_id)

    async def fake_get_profile(client, access_token):  # type: ignore[no-untyped-def]
        return {"historyId": "500"}

    monkeypatch.setattr(sync_module, "list_message_ids", fake_list_message_ids)
    monkeypatch.setattr(sync_module, "get_message", fake_get_message)
    monkeypatch.setattr(sync_module, "get_profile", fake_get_profile)

    async with session_factory() as db:
        connection = await _make_connection(db)
        sync_run = GmailSyncRun(connection_id=connection.id, sync_type="backfill", status="pending")
        db.add(sync_run)
        await db.commit()

        await sync_module.run_sync(db, sync_run.id)

        await db.refresh(sync_run)
        await db.refresh(connection)
        assert sync_run.status == "completed"
        assert sync_run.messages_fetched == 3
        assert sync_run.messages_stored == 3
        assert connection.last_history_id == "500"
        assert connection.status == "connected"

        rows = await db.execute(
            select(EmailMessage).where(EmailMessage.connection_id == connection.id)
        )
        stored = rows.scalars().all()
        assert {m.gmail_message_id for m in stored} == {"m1", "m2", "m3"}


async def test_backfill_skips_already_stored_messages(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    fetched_ids: list[str] = []

    async def fake_list_message_ids(client, access_token, *, query=None, page_token=None):  # type: ignore[no-untyped-def]
        return ["existing1", "new1"], None

    async def fake_get_message(client, access_token, message_id):  # type: ignore[no-untyped-def]
        fetched_ids.append(message_id)
        return _fake_message(message_id)

    async def fake_get_profile(client, access_token):  # type: ignore[no-untyped-def]
        return {"historyId": "1"}

    monkeypatch.setattr(sync_module, "list_message_ids", fake_list_message_ids)
    monkeypatch.setattr(sync_module, "get_message", fake_get_message)
    monkeypatch.setattr(sync_module, "get_profile", fake_get_profile)

    async with session_factory() as db:
        connection = await _make_connection(db)
        db.add(
            EmailMessage(
                connection_id=connection.id,
                gmail_message_id="existing1",
                thread_id="t",
                snippet="",
                to_addresses=[],
                label_ids=[],
            )
        )
        sync_run = GmailSyncRun(connection_id=connection.id, sync_type="backfill", status="pending")
        db.add(sync_run)
        await db.commit()

        await sync_module.run_sync(db, sync_run.id)

        assert fetched_ids == ["new1"]  # already-stored message never re-fetched


async def test_incremental_falls_back_to_backfill_when_history_too_old(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_list_history(client, access_token, *, start_history_id, page_token=None):  # type: ignore[no-untyped-def]
        return [], None, True

    async def fake_list_message_ids(client, access_token, *, query=None, page_token=None):  # type: ignore[no-untyped-def]
        return ["fresh1"], None

    async def fake_get_message(client, access_token, message_id):  # type: ignore[no-untyped-def]
        return _fake_message(message_id)

    async def fake_get_profile(client, access_token):  # type: ignore[no-untyped-def]
        return {"historyId": "999"}

    monkeypatch.setattr(sync_module, "list_history", fake_list_history)
    monkeypatch.setattr(sync_module, "list_message_ids", fake_list_message_ids)
    monkeypatch.setattr(sync_module, "get_message", fake_get_message)
    monkeypatch.setattr(sync_module, "get_profile", fake_get_profile)

    async with session_factory() as db:
        connection = await _make_connection(db, last_history_id="100")
        sync_run = GmailSyncRun(
            connection_id=connection.id, sync_type="incremental", status="pending"
        )
        db.add(sync_run)
        await db.commit()

        await sync_module.run_sync(db, sync_run.id)

        await db.refresh(sync_run)
        await db.refresh(connection)
        assert sync_run.status == "completed"
        assert sync_run.sync_type == "backfill"
        assert connection.last_history_id == "999"


async def test_sync_marks_needs_reauth_when_refresh_fails(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_refresh(refresh_token: str) -> None:
        raise ReauthRequiredError("expired")

    monkeypatch.setattr(sync_module, "refresh_access_token", fake_refresh)

    async with session_factory() as db:
        connection = await _make_connection(db, expired=True)
        sync_run = GmailSyncRun(connection_id=connection.id, sync_type="backfill", status="pending")
        db.add(sync_run)
        await db.commit()

        await sync_module.run_sync(db, sync_run.id)

        await db.refresh(sync_run)
        await db.refresh(connection)
        assert sync_run.status == "failed"
        assert connection.status == "needs_reauth"


async def test_message_fetch_failure_is_skipped_not_fatal(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_list_message_ids(client, access_token, *, query=None, page_token=None):  # type: ignore[no-untyped-def]
        return ["good1", "bad1"], None

    async def fake_get_message(client, access_token, message_id):  # type: ignore[no-untyped-def]
        if message_id == "bad1":
            raise GmailApiError("404")
        return _fake_message(message_id)

    async def fake_get_profile(client, access_token):  # type: ignore[no-untyped-def]
        return {"historyId": "1"}

    monkeypatch.setattr(sync_module, "list_message_ids", fake_list_message_ids)
    monkeypatch.setattr(sync_module, "get_message", fake_get_message)
    monkeypatch.setattr(sync_module, "get_profile", fake_get_profile)

    async with session_factory() as db:
        connection = await _make_connection(db)
        sync_run = GmailSyncRun(connection_id=connection.id, sync_type="backfill", status="pending")
        db.add(sync_run)
        await db.commit()

        await sync_module.run_sync(db, sync_run.id)

        await db.refresh(sync_run)
        assert sync_run.status == "completed"
        assert sync_run.messages_stored == 1

        rows = await db.execute(
            select(EmailMessage).where(EmailMessage.connection_id == connection.id)
        )
        stored = rows.scalars().all()
        assert {m.gmail_message_id for m in stored} == {"good1"}
