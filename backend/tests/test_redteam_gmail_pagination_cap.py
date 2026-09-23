"""Red-team Track A, item 8: Gmail sync had no bound on how many list-API pages a single
backfill/incremental run would follow (Calendar and GitHub sync both already cap total
requests per run) — an unbounded `while True` on `page_token`. Fixed with the same
"generous but finite" ceiling pattern; these tests force a page_token that never ends and
confirm the loop still stops.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.db.models import User
from app.gmail import sync as sync_module
from app.gmail.crypto import encrypt_token
from app.gmail.models import GmailConnection, GmailSyncRun


async def _make_connection(db: AsyncSession, **overrides: object) -> GmailConnection:
    user = User(email=f"gmail-pagecap-{uuid.uuid4()}@example.com", hashed_password="x")
    db.add(user)
    await db.flush()
    fields: dict[str, object] = {
        "user_id": user.id,
        "google_email": "aziz@gmail.com",
        "access_token_encrypted": encrypt_token("fake-access-token"),
        "refresh_token_encrypted": encrypt_token("fake-refresh-token"),
        "token_expires_at": datetime.now(UTC) + timedelta(hours=1),
        "granted_scopes": "https://www.googleapis.com/auth/gmail.readonly",
        "status": "connected",
        **overrides,
    }
    connection = GmailConnection(**fields)  # type: ignore[arg-type]
    db.add(connection)
    await db.flush()
    return connection


async def _noop(*args: object, **kwargs: object) -> None:
    return None


async def test_backfill_paging_stops_at_the_cap_instead_of_looping_forever(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"count": 0}

    async def never_ending_pages(
        client: object, access_token: str, *, query: str, page_token: str | None
    ) -> tuple[list[str], str]:
        calls["count"] += 1
        return [f"id-{calls['count']}"], f"token-{calls['count']}"  # never a falsy token

    monkeypatch.setattr(sync_module, "list_message_ids", never_ending_pages)
    monkeypatch.setattr(sync_module, "_fetch_and_store_new_messages", _noop)
    monkeypatch.setattr(sync_module, "_update_history_cursor", _noop)

    async with session_factory() as db:
        connection = await _make_connection(db)
        sync_run = GmailSyncRun(
            connection_id=connection.id, sync_type="backfill", status="running"
        )
        db.add(sync_run)
        await db.commit()

        await sync_module._run_backfill(
            db, object(), connection, "fake-token", sync_run, get_settings()
        )

    assert calls["count"] == sync_module.MAX_LIST_PAGES  # stopped, not infinite


async def test_incremental_paging_stops_at_the_cap_instead_of_looping_forever(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"count": 0}

    async def never_ending_pages(
        client: object, access_token: str, *, start_history_id: str, page_token: str | None
    ) -> tuple[list[str], str, bool]:
        calls["count"] += 1
        return [f"id-{calls['count']}"], f"token-{calls['count']}", False

    monkeypatch.setattr(sync_module, "list_history", never_ending_pages)
    monkeypatch.setattr(sync_module, "_fetch_and_store_new_messages", _noop)
    monkeypatch.setattr(sync_module, "_update_history_cursor", _noop)

    async with session_factory() as db:
        connection = await _make_connection(db, last_history_id="12345")
        sync_run = GmailSyncRun(
            connection_id=connection.id, sync_type="incremental", status="running"
        )
        db.add(sync_run)
        await db.commit()

        too_old = await sync_module._run_incremental(
            db, object(), connection, "fake-token", sync_run, get_settings()
        )

    assert too_old is False
    assert calls["count"] == sync_module.MAX_LIST_PAGES  # stopped, not infinite
