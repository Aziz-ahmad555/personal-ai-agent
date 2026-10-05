"""Sync, events and the manual classify override through the API."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from calendar_fake import FakeCalendar, event
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.models import AuditLog
from app.calendar import oauth, sync
from app.calendar.models import CalendarConnection, CalendarSyncRun
from app.career.models import Application, JobPosting
from app.db.models import User
from app.gmail.crypto import encrypt_token

OWNER = "profile-owner@example.com"


async def _connect(
    session_factory: async_sessionmaker[AsyncSession], email: str = OWNER, **overrides: object
) -> uuid.UUID:
    async with session_factory() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one()
        fields: dict[str, object] = {
            "user_id": user.id,
            "google_email": "person-01@example.com",
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
        return connection.id


async def _tracked_application(
    session_factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID
) -> uuid.UUID:
    async with session_factory() as db:
        job = JobPosting(
            user_id=user_id,
            source_channel="manual_paste",
            title="ML Engineer",
            company_name="Acme Corp",
            company_domain="example.com",
            description_text="x",
        )
        db.add(job)
        await db.flush()
        application = Application(user_id=user_id, job_posting_id=job.id, status="applied")
        db.add(application)
        await db.commit()
        return application.id


async def _sync(
    client: AsyncClient,
    headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    fake: FakeCalendar | None = None,
) -> dict:
    fake = fake or FakeCalendar()
    if not fake.routes:
        fake.events_page([event("e1", summary="Interview with Acme Corp")])
    monkeypatch.setattr(sync.httpx, "AsyncClient", fake.client_factory())
    response = await client.post("/calendar/sync", headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


async def _events(client: AsyncClient, headers: dict[str, str]) -> list[dict]:
    response = await client.get("/calendar/events", headers=headers)
    assert response.status_code == 200
    return response.json()


# --- access -----------------------------------------------------------------------------


async def test_every_endpoint_requires_auth(client: AsyncClient) -> None:
    assert (await client.post("/calendar/sync")).status_code == 401
    assert (await client.get("/calendar/sync")).status_code == 401
    assert (await client.get("/calendar/events")).status_code == 401
    assert (
        await client.post(f"/calendar/events/{uuid.uuid4()}/classify", json={"kind": "other"})
    ).status_code == 401


async def test_nothing_works_before_calendar_is_connected(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    for method, path in (
        ("post", "/calendar/sync"),
        ("get", "/calendar/sync"),
        ("get", "/calendar/events"),
    ):
        response = await getattr(client, method)(path, headers=auth_headers)
        assert response.status_code == 404, path


# --- sync -------------------------------------------------------------------------------


async def test_a_sync_needs_a_working_connection(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _connect(session_factory, status="needs_reauth")

    response = await client.post("/calendar/sync", headers=auth_headers)

    assert response.status_code == 409
    assert "connect or reconnect" in response.json()["detail"]


async def test_a_sync_runs_and_reports_its_results(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _connect(session_factory)

    started = await _sync(client, auth_headers, monkeypatch)

    assert started["status"] in ("pending", "running", "completed")
    runs = (await client.get("/calendar/sync", headers=auth_headers)).json()
    assert [r["status"] for r in runs] == ["completed"]
    assert runs[0]["events_seen"] == 1
    assert runs[0]["error"] is None


async def test_a_second_sync_is_refused_while_one_is_running(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    connection_id = await _connect(session_factory)
    async with session_factory() as db:
        db.add(CalendarSyncRun(connection_id=connection_id, status="running"))
        await db.commit()

    response = await client.post("/calendar/sync", headers=auth_headers)

    assert response.status_code == 409
    assert "already running" in response.json()["detail"]


async def test_an_orphaned_run_is_reported_failed_and_does_not_block_a_new_sync(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection_id = await _connect(session_factory)
    async with session_factory() as db:
        db.add(
            CalendarSyncRun(
                connection_id=connection_id,
                status="running",
                started_at=datetime.now(UTC) - timedelta(minutes=30),
            )
        )
        await db.commit()

    runs = (await client.get("/calendar/sync", headers=auth_headers)).json()
    assert runs[0]["status"] == "failed"
    assert "server was probably restarted" in runs[0]["error"]

    await _sync(client, auth_headers, monkeypatch)  # a new sync is allowed


# --- events -------------------------------------------------------------------------------


async def test_events_show_the_classification_and_evidence(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _connect(session_factory)
    await _sync(client, auth_headers, monkeypatch)

    events = await _events(client, auth_headers)

    assert len(events) == 1
    assert events[0]["kind"] == "interview"
    assert events[0]["match_reason"] == "interview"
    assert events[0]["user_confirmed"] is False
    assert "token" not in str(events).lower()


async def test_a_linked_application_is_included(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = await _connect_and_get_user(session_factory)
    application_id = await _tracked_application(session_factory, user_id)
    fake = FakeCalendar()
    fake.events_page(
        [event("e1", summary="Interview", attendees=[{"email": "person-02@example.com"}])]
    )

    await _sync(client, auth_headers, monkeypatch, fake)
    events = await _events(client, auth_headers)

    assert events[0]["application"]["id"] == str(application_id)
    assert events[0]["application"]["company_name"] == "Acme Corp"
    assert "example.com" in events[0]["application_match_reason"]


async def _connect_and_get_user(session_factory: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    async with session_factory() as db:
        user = (await db.execute(select(User).where(User.email == OWNER))).scalar_one()
    await _connect(session_factory)
    return user.id


# --- classify override ----------------------------------------------------------------------


async def test_classifying_an_event_overrides_it_and_is_never_reclassified(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _connect(session_factory)
    fake = FakeCalendar()
    fake.events_page([event("e1", summary="Team lunch")])
    await _sync(client, auth_headers, monkeypatch, fake)
    events = await _events(client, auth_headers)
    event_id = events[0]["id"]

    response = await client.post(
        f"/calendar/events/{event_id}/classify",
        headers=auth_headers,
        json={"kind": "interview"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "interview"
    assert body["user_confirmed"] is True

    # Re-sync with clearly non-interview text — the override must survive.
    fake.events_page([event("e1", summary="Definitely just lunch, nothing else")])
    await _sync(client, auth_headers, monkeypatch, fake)
    events = await _events(client, auth_headers)
    assert events[0]["kind"] == "interview"
    assert events[0]["user_confirmed"] is True


async def test_classifying_can_link_to_a_tracked_application(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = await _connect_and_get_user(session_factory)
    application_id = await _tracked_application(session_factory, user_id)
    await _sync(client, auth_headers, monkeypatch)
    event_id = (await _events(client, auth_headers))[0]["id"]

    response = await client.post(
        f"/calendar/events/{event_id}/classify",
        headers=auth_headers,
        json={"kind": "interview", "application_id": str(application_id)},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["application"]["id"] == str(application_id)
    assert body["application_match_reason"] == "Linked by you"


async def test_classifying_with_someone_elses_application_id_is_rejected(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.auth.security import hash_password

    async with session_factory() as db:
        other = User(email="other@example.com", hashed_password=hash_password("x-y-z-123456"))
        db.add(other)
        await db.commit()
        await db.refresh(other)
    foreign_application_id = await _tracked_application(session_factory, other.id)
    await _connect(session_factory)
    await _sync(client, auth_headers, monkeypatch)
    event_id = (await _events(client, auth_headers))[0]["id"]

    response = await client.post(
        f"/calendar/events/{event_id}/classify",
        headers=auth_headers,
        json={"kind": "interview", "application_id": str(foreign_application_id)},
    )

    assert response.status_code == 404


async def test_classify_is_audited_as_green(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _connect(session_factory)
    await _sync(client, auth_headers, monkeypatch)
    event_id = (await _events(client, auth_headers))[0]["id"]

    await client.post(
        f"/calendar/events/{event_id}/classify", headers=auth_headers, json={"kind": "deadline"}
    )

    async with session_factory() as db:
        entry = (
            await db.execute(select(AuditLog).where(AuditLog.action == "calendar.event.classified"))
        ).scalar_one()
    assert entry.risk_level == "green"
    assert entry.evidence["kind"] == "deadline"


async def test_events_and_classify_are_isolated_per_user(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.auth.security import hash_password

    async with session_factory() as db:
        other = User(email="other@example.com", hashed_password=hash_password("x-y-z-123456"))
        db.add(other)
        await db.commit()
    other_connection_id = await _connect(session_factory, email="other@example.com")
    fake = FakeCalendar()
    fake.events_page([event("e-other")])
    monkeypatch.setattr(sync.httpx, "AsyncClient", fake.client_factory())
    async with session_factory() as db:
        run = await sync.start_run(db, other_connection_id)
        await sync.run_sync(db, run.id)

    # The owner (auth_headers' user) has no connection at all yet.
    assert (await client.get("/calendar/events", headers=auth_headers)).status_code == 404


# --- disconnect purges synced data but not applications --------------------------------------


async def test_disconnect_can_purge_events_but_never_touches_applications(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def revoke(token: str) -> bool:
        return True

    monkeypatch.setattr(oauth, "revoke_token", revoke)
    user_id = await _connect_and_get_user(session_factory)
    application_id = await _tracked_application(session_factory, user_id)
    await _sync(client, auth_headers, monkeypatch)

    response = await client.delete("/calendar/connection?purge_data=true", headers=auth_headers)

    assert response.status_code == 200
    async with session_factory() as db:
        from app.calendar.models import CalendarEvent

        assert (await db.execute(select(CalendarEvent))).first() is None
        assert (await db.execute(select(CalendarSyncRun))).first() is None
        assert await db.get(Application, application_id) is not None  # untouched
