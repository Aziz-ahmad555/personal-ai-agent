"""The read-only Calendar reads and the sync that turns them into a stored snapshot with
deterministic classification. All Calendar HTTP is faked (see calendar_fake.py): no test
reaches the real API."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from calendar_fake import FakeCalendar, event, ok
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.models import AuditLog
from app.calendar import client as gcal
from app.calendar import oauth, sync
from app.calendar.models import CalendarConnection, CalendarEvent, CalendarSyncRun
from app.career.models import Application, JobPosting
from app.db.models import User
from app.gmail.crypto import encrypt_token

# --- the client's reads ---------------------------------------------------------------------


def _api(handler) -> httpx.AsyncClient:  # type: ignore[no-untyped-def]
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_list_events_sends_a_time_window_and_orders_by_start_time() -> None:
    fake = FakeCalendar()
    fake.events_page([event("e1")])

    async with _api(fake.handler) as http:
        page = await gcal.list_events(
            http, "token", time_min="2026-09-01T00:00:00Z", time_max="2026-10-01T00:00:00Z"
        )

    assert [e["id"] for e in page.events] == ["e1"]
    query = fake.queries[0]
    assert query["singleEvents"] == ["true"]
    assert query["orderBy"] == ["startTime"]
    assert query["timeMin"] == ["2026-09-01T00:00:00Z"]


async def test_list_events_with_a_sync_token_does_not_send_a_time_window() -> None:
    fake = FakeCalendar()
    fake.events_page([], next_sync_token="tok-2")

    async with _api(fake.handler) as http:
        page = await gcal.list_events(http, "token", sync_token="tok-1")

    assert page.next_sync_token == "tok-2"
    query = fake.queries[0]
    assert query["syncToken"] == ["tok-1"]
    assert "timeMin" not in query
    assert "orderBy" not in query


async def test_a_401_is_an_auth_error_and_a_410_is_a_sync_token_error() -> None:
    async with _api(lambda r: httpx.Response(401)) as http:
        with pytest.raises(gcal.CalendarAuthError):
            await gcal.list_events(http, "bad")
    async with _api(lambda r: httpx.Response(410)) as http:
        with pytest.raises(gcal.SyncTokenExpiredError):
            await gcal.list_events(http, "token", sync_token="stale")
    async with _api(lambda r: httpx.Response(503)) as http:
        with pytest.raises(gcal.CalendarApiError) as caught:
            await gcal.list_events(http, "token")
        assert not isinstance(caught.value, gcal.CalendarAuthError | gcal.SyncTokenExpiredError)


async def test_an_unexpected_events_shape_is_rejected() -> None:
    async with _api(lambda r: ok({"items": "not-a-list"})) as http:
        with pytest.raises(gcal.CalendarApiError):
            await gcal.list_events(http, "token")


# --- the sync ---------------------------------------------------------------------------------


async def _connection(
    session_factory: async_sessionmaker[AsyncSession], **overrides: object
) -> CalendarConnection:
    async with session_factory() as db:
        user = (await db.execute(select(User))).scalars().first()
        if user is None:
            user = User(email="owner@example.com", hashed_password="x")
            db.add(user)
            await db.flush()
        fields: dict[str, object] = {
            "user_id": user.id,
            "google_email": "aziz@gmail.com",
            "access_token_encrypted": encrypt_token("access-token"),
            "refresh_token_encrypted": encrypt_token("refresh-token"),
            "token_expires_at": datetime.now(UTC) + timedelta(hours=1),
            "granted_scopes": oauth.CALENDAR_READONLY_SCOPE,
            "status": "connected",
            **overrides,
        }
        connection = CalendarConnection(**fields)  # type: ignore[arg-type]
        db.add(connection)
        await db.commit()
        return connection


async def _tracked_application(
    session_factory: async_sessionmaker[AsyncSession],
    user_id,  # type: ignore[no-untyped-def]
    *,
    company_name: str = "Acme Corp",
    company_domain: str | None = "acme.com",
) -> str:
    async with session_factory() as db:
        job = JobPosting(
            user_id=user_id,
            source_channel="manual_paste",
            title="ML Engineer",
            company_name=company_name,
            company_domain=company_domain,
            description_text="x",
        )
        db.add(job)
        await db.flush()
        application = Application(user_id=user_id, job_posting_id=job.id, status="applied")
        db.add(application)
        await db.commit()
        return str(application.id)


async def _run(
    session_factory: async_sessionmaker[AsyncSession],
    fake: FakeCalendar,
    monkeypatch: pytest.MonkeyPatch,
    connection: CalendarConnection,
) -> CalendarSyncRun:
    monkeypatch.setattr(sync.httpx, "AsyncClient", fake.client_factory())
    async with session_factory() as db:
        run = await sync.start_run(db, connection.id)
        await sync.run_sync(db, run.id)
    async with session_factory() as db:
        return await db.get(CalendarSyncRun, run.id)  # type: ignore[return-value]


async def _events(session_factory: async_sessionmaker[AsyncSession]) -> dict[str, CalendarEvent]:
    async with session_factory() as db:
        rows = (await db.execute(select(CalendarEvent))).scalars().all()
    return {r.google_event_id: r for r in rows}


async def test_a_full_sync_stores_events_and_classifies_them(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = await _connection(session_factory)
    fake = FakeCalendar()
    fake.events_page(
        [
            event("e1", summary="Technical interview with Acme"),
            event("e2", summary="Team lunch"),
        ],
        next_sync_token="sync-1",
    )

    run = await _run(session_factory, fake, monkeypatch, connection)

    assert run.status == "completed"
    assert (run.events_seen, run.events_stored) == (2, 2)
    events = await _events(session_factory)
    assert events["e1"].kind == "interview"
    assert events["e1"].match_reason == "technical interview"
    assert events["e2"].kind == "other"
    async with session_factory() as db:
        stored = await db.get(CalendarConnection, connection.id)
        assert stored.sync_token == "sync-1"  # type: ignore[union-attr]
        assert stored.last_synced_at is not None  # type: ignore[union-attr]


async def test_an_event_is_linked_to_a_tracked_application_by_domain(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = await _connection(session_factory)
    application_id = await _tracked_application(session_factory, connection.user_id)
    fake = FakeCalendar()
    fake.events_page(
        [
            event(
                "e1",
                summary="Interview",
                attendees=[{"email": "jane@acme.com"}],
            )
        ]
    )

    await _run(session_factory, fake, monkeypatch, connection)

    events = await _events(session_factory)
    assert str(events["e1"].application_id) == application_id
    assert "acme.com" in (events["e1"].application_match_reason or "")


async def test_all_day_events_are_parsed_as_such(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = await _connection(session_factory)
    fake = FakeCalendar()
    fake.events_page([event("e1", summary="Apply by Friday", all_day=True, start="2026-09-26")])

    await _run(session_factory, fake, monkeypatch, connection)

    events = await _events(session_factory)
    assert events["e1"].is_all_day is True
    assert events["e1"].kind == "deadline"
    assert events["e1"].start_at.year == 2026  # type: ignore[union-attr]


async def test_a_cancelled_event_is_removed_not_stored(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = await _connection(session_factory)
    fake = FakeCalendar()
    fake.events_page([event("e1")])
    await _run(session_factory, fake, monkeypatch, connection)
    assert "e1" in await _events(session_factory)

    fake.events_page([event("e1", status="cancelled")])
    await _run(session_factory, fake, monkeypatch, connection)

    assert "e1" not in await _events(session_factory)


async def test_a_second_sync_is_incremental_and_uses_the_stored_token(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = await _connection(session_factory)
    fake = FakeCalendar()
    fake.events_page([event("e1")], next_sync_token="tok-1")
    await _run(session_factory, fake, monkeypatch, connection)

    fake.events_page([event("e2")], next_sync_token="tok-2")
    async with session_factory() as db:
        refreshed = await db.get(CalendarConnection, connection.id)
    await _run(session_factory, fake, monkeypatch, refreshed)  # type: ignore[arg-type]

    assert fake.queries[-1]["syncToken"] == ["tok-1"]
    events = await _events(session_factory)
    assert set(events) == {"e1", "e2"}


async def test_an_expired_sync_token_falls_back_to_a_full_sync(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = await _connection(session_factory, sync_token="stale-token")
    fake = FakeCalendar()

    calls = {"n": 0}

    def handler(request: httpx.Request):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(410, json={"error": {"message": "gone"}})
        return ok({"items": [event("e1")], "nextSyncToken": "fresh-token"})

    fake.routes["/calendar/v3/calendars/primary/events"] = handler

    run = await _run(session_factory, fake, monkeypatch, connection)

    assert run.status == "completed"
    assert any("full sync" in w for w in run.warnings)
    async with session_factory() as db:
        stored = await db.get(CalendarConnection, connection.id)
        assert stored.sync_token == "fresh-token"  # type: ignore[union-attr]


async def test_a_user_confirmed_event_is_never_reclassified(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = await _connection(session_factory)
    fake = FakeCalendar()
    fake.events_page([event("e1", summary="Team lunch")])
    await _run(session_factory, fake, monkeypatch, connection)
    async with session_factory() as db:
        row = (await db.execute(select(CalendarEvent))).scalar_one()
        row.kind = "interview"
        row.user_confirmed = True
        await db.commit()

    # A later sync sees the same event, now clearly NOT an interview by its own text — but
    # the user's correction must survive.
    fake.events_page([event("e1", summary="Team lunch, definitely not an interview")])
    async with session_factory() as db:
        refreshed = await db.get(CalendarConnection, connection.id)
    await _run(session_factory, fake, monkeypatch, refreshed)  # type: ignore[arg-type]

    events = await _events(session_factory)
    assert events["e1"].kind == "interview"
    assert events["e1"].user_confirmed is True
    assert events["e1"].summary == "Team lunch, definitely not an interview"  # facts still refresh


async def test_pagination_is_followed_across_multiple_pages(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = await _connection(session_factory)
    fake = FakeCalendar()

    def handler(request: httpx.Request):  # type: ignore[no-untyped-def]
        query = dict(request.url.params)
        if query.get("pageToken") == "page-2":
            return ok({"items": [event("e2")], "nextSyncToken": "final-token"})
        return ok({"items": [event("e1")], "nextPageToken": "page-2"})

    fake.routes["/calendar/v3/calendars/primary/events"] = handler

    run = await _run(session_factory, fake, monkeypatch, connection)

    assert run.events_seen == 2
    assert set(await _events(session_factory)) == {"e1", "e2"}
    async with session_factory() as db:
        stored = await db.get(CalendarConnection, connection.id)
        assert stored.sync_token == "final-token"  # type: ignore[union-attr]


async def test_the_request_budget_stops_a_sync_and_reports_it(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = await _connection(session_factory)
    fake = FakeCalendar()
    page = {"n": 0}

    def handler(request: httpx.Request):  # type: ignore[no-untyped-def]
        page["n"] += 1
        return ok({"items": [event(f"e{page['n']}")], "nextPageToken": f"p{page['n']}"})

    fake.routes["/calendar/v3/calendars/primary/events"] = handler
    monkeypatch.setattr(sync, "MAX_REQUESTS", 3)

    run = await _run(session_factory, fake, monkeypatch, connection)

    assert run.status == "completed"
    assert any("Stopped early" in w for w in run.warnings)
    assert page["n"] == 3


async def test_a_rejected_token_fails_the_run_and_marks_needs_reauth(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = await _connection(session_factory)
    fake = FakeCalendar()
    fake.routes["/calendar/v3/calendars/primary/events"] = httpx.Response(401)

    run = await _run(session_factory, fake, monkeypatch, connection)

    assert run.status == "failed"
    assert "reconnect" in (run.error or "").lower()
    async with session_factory() as db:
        stored = await db.get(CalendarConnection, connection.id)
        failed = (
            await db.execute(select(AuditLog).where(AuditLog.action == "calendar.sync_failed"))
        ).scalar_one()
    assert stored.status == "needs_reauth"  # type: ignore[union-attr]
    assert failed.status == "failed"


async def test_a_disconnected_connection_fails_the_run_without_calling_google(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = await _connection(
        session_factory, status="disconnected", access_token_encrypted=None
    )
    fake = FakeCalendar()

    run = await _run(session_factory, fake, monkeypatch, connection)

    assert run.status == "failed"
    assert "isn't connected" in (run.error or "")
    assert fake.requests == []


async def test_a_sync_is_audited_without_any_token(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = await _connection(session_factory)
    fake = FakeCalendar()
    fake.events_page([event("e1")])

    await _run(session_factory, fake, monkeypatch, connection)

    async with session_factory() as db:
        entry = (
            await db.execute(select(AuditLog).where(AuditLog.action == "calendar.synced"))
        ).scalar_one()
    assert entry.risk_level == "green"
    assert entry.evidence["events_seen"] == 1
    assert "access-token" not in str(entry.evidence) + entry.summary


def test_a_run_is_active_until_it_is_old_enough_to_presume_dead() -> None:
    now = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)
    fresh = CalendarSyncRun(status="running", started_at=now - timedelta(minutes=2))
    old = CalendarSyncRun(status="running", started_at=now - timedelta(minutes=11))
    done = CalendarSyncRun(status="completed", started_at=now - timedelta(minutes=30))

    assert sync.is_active(fresh, now=now) and not sync.is_stalled(fresh, now=now)
    assert sync.is_stalled(old, now=now) and not sync.is_active(old, now=now)
    assert not sync.is_active(done, now=now) and not sync.is_stalled(done, now=now)


async def test_a_database_failure_mid_sync_is_still_recorded_on_the_run(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def boom(db, connection, raw, candidates):  # type: ignore[no-untyped-def]
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(sync, "_upsert_event", boom)
    fake = FakeCalendar()
    fake.events_page([event("e1")])

    run = await _run(session_factory, fake, monkeypatch, await _connection(session_factory))

    assert run.status == "failed"
    assert run.completed_at is not None
