"""Phase 11: the background scheduler. Per the approved plan, this tests each scheduled
callback's logic directly (does it call the right service function, for the right rows, with
trigger="scheduled") rather than real timers — build_scheduler's own interval wiring gets one
lightweight check that all five jobs are registered with the configured intervals.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from apscheduler.triggers.interval import IntervalTrigger
from calendar_fake import FakeCalendar
from github_fake import FakeGitHub
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.models import AuditLog
from app.calendar import oauth as calendar_oauth
from app.calendar import sync as calendar_sync
from app.calendar.models import CalendarConnection, CalendarSyncRun
from app.career import discovery as discovery_module
from app.career.boards import BoardApiError, RawPosting
from app.career.models import JobBoardFeed, JobPosting
from app.config import Settings
from app.core.scheduler import (
    CALENDAR_SYNC_JOB_ID,
    DIGEST_GENERATION_JOB_ID,
    GITHUB_SYNC_JOB_ID,
    GMAIL_SYNC_JOB_ID,
    JOB_FEED_POLL_JOB_ID,
    build_scheduler,
    run_scheduled_calendar_syncs,
    run_scheduled_digest_generation,
    run_scheduled_feed_polls,
    run_scheduled_github_syncs,
    run_scheduled_gmail_syncs,
)
from app.db.models import User
from app.github import sync as github_sync
from app.github.models import GithubConnection, GithubSyncRun
from app.gmail import sync as gmail_sync
from app.gmail.crypto import encrypt_token
from app.gmail.models import GmailConnection, GmailSyncRun
from app.reporting.models import WeeklyDigest


async def _make_user(db: AsyncSession) -> User:
    user = User(email=f"scheduler-test-{uuid.uuid4()}@example.com", hashed_password="x")
    db.add(user)
    await db.flush()
    return user


# --- build_scheduler: interval wiring only, not real firing ---------------------------------


def test_build_scheduler_registers_all_five_jobs_with_configured_intervals() -> None:
    settings = Settings.model_construct(
        app_secret_key="x" * 32,
        database_url="sqlite+aiosqlite:///:memory:",
        github_sync_interval_hours=12,
        job_feed_poll_interval_hours=3,
        digest_generation_interval_days=2,
        gmail_sync_interval_hours=5,
        calendar_sync_interval_hours=7,
    )

    scheduler = build_scheduler(settings)
    jobs = {job.id: job for job in scheduler.get_jobs()}

    assert set(jobs) == {
        GITHUB_SYNC_JOB_ID,
        JOB_FEED_POLL_JOB_ID,
        DIGEST_GENERATION_JOB_ID,
        GMAIL_SYNC_JOB_ID,
        CALENDAR_SYNC_JOB_ID,
    }
    assert isinstance(jobs[GITHUB_SYNC_JOB_ID].trigger, IntervalTrigger)
    assert jobs[GITHUB_SYNC_JOB_ID].trigger.interval == timedelta(hours=12)
    assert jobs[JOB_FEED_POLL_JOB_ID].trigger.interval == timedelta(hours=3)
    assert jobs[DIGEST_GENERATION_JOB_ID].trigger.interval == timedelta(days=2)
    assert jobs[GMAIL_SYNC_JOB_ID].trigger.interval == timedelta(hours=5)
    assert jobs[CALENDAR_SYNC_JOB_ID].trigger.interval == timedelta(hours=7)


# --- run_scheduled_github_syncs --------------------------------------------------------------


async def _connection(
    session_factory: async_sessionmaker[AsyncSession], **overrides: object
) -> GithubConnection:
    async with session_factory() as db:
        user = await _make_user(db)
        fields: dict[str, object] = {
            "user_id": user.id,
            "github_login": "me",
            "github_user_id": 1,
            "access_token_encrypted": encrypt_token("access-token"),
            "refresh_token_encrypted": encrypt_token("refresh-token"),
            "token_expires_at": datetime.now(UTC) + timedelta(hours=4),
            "installations": [],
            "status": "connected",
            **overrides,
        }
        connection = GithubConnection(**fields)  # type: ignore[arg-type]
        db.add(connection)
        await db.commit()
        return connection


async def test_scheduled_github_sync_runs_for_every_connected_connection(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeGitHub()
    fake.account()
    monkeypatch.setattr(github_sync.httpx, "AsyncClient", fake.client_factory())
    connection = await _connection(session_factory)

    await run_scheduled_github_syncs()

    async with session_factory() as db:
        run = (
            await db.execute(
                select(GithubSyncRun).where(GithubSyncRun.connection_id == connection.id)
            )
        ).scalar_one()
        entry = (
            await db.execute(select(AuditLog).where(AuditLog.action == "github.synced"))
        ).scalar_one()
    assert run.status == "completed"
    assert entry.evidence["trigger"] == "scheduled"


async def test_scheduled_github_sync_skips_a_disconnected_connection(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeGitHub()
    monkeypatch.setattr(github_sync.httpx, "AsyncClient", fake.client_factory())
    connection = await _connection(
        session_factory, status="disconnected", access_token_encrypted=None
    )

    await run_scheduled_github_syncs()

    async with session_factory() as db:
        runs = (
            (
                await db.execute(
                    select(GithubSyncRun).where(GithubSyncRun.connection_id == connection.id)
                )
            )
            .scalars()
            .all()
        )
    assert runs == []
    assert fake.requests == []


async def test_scheduled_github_sync_skips_a_connection_with_an_active_run(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeGitHub()
    monkeypatch.setattr(github_sync.httpx, "AsyncClient", fake.client_factory())
    connection = await _connection(session_factory)
    async with session_factory() as db:
        db.add(
            GithubSyncRun(
                connection_id=connection.id, status="running", started_at=datetime.now(UTC)
            )
        )
        await db.commit()

    await run_scheduled_github_syncs()

    assert fake.requests == []  # never even started a second run


# --- run_scheduled_feed_polls -----------------------------------------------------------------


async def test_scheduled_feed_poll_creates_postings_tagged_as_scheduled(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    posting = RawPosting(
        external_id="1",
        title="Engineer A",
        location="Remote",
        url="https://acme.example.com/jobs/1",
        posted_at="2026-09-01T00:00:00Z",
        description="Job A description text.",
        raw={"id": "1"},
    )

    async def fake_fetch_greenhouse(client: object, company_slug: str) -> list[RawPosting]:
        return [posting]

    monkeypatch.setattr(discovery_module, "fetch_greenhouse_postings", fake_fetch_greenhouse)

    async with session_factory() as db:
        user = await _make_user(db)
        feed = JobBoardFeed(user_id=user.id, board="greenhouse", company_slug="acme")
        db.add(feed)
        await db.commit()
        feed_id = feed.id

    await run_scheduled_feed_polls()

    async with session_factory() as db:
        postings = (
            (await db.execute(select(JobPosting).where(JobPosting.user_id == user.id)))
            .scalars()
            .all()
        )
        entry = (
            await db.execute(select(AuditLog).where(AuditLog.action == "career.feed.polled"))
        ).scalar_one()
        feed = await db.get(JobBoardFeed, feed_id)
    assert len(postings) == 1
    assert entry.evidence["trigger"] == "scheduled"
    assert feed.last_poll_error is None  # type: ignore[union-attr]


async def test_a_failing_feed_does_not_stop_the_rest_of_the_scheduled_poll(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    good_posting = RawPosting(
        external_id="1",
        title="Engineer A",
        location="Remote",
        url="https://good.example.com/jobs/1",
        posted_at="2026-09-01T00:00:00Z",
        description="Good posting description.",
        raw={"id": "1"},
    )

    async def failing_fetch(client: object, company_slug: str) -> list[RawPosting]:
        raise BoardApiError("Greenhouse returned HTTP 404 for 'bad'")

    async def working_fetch(client: object, company_slug: str) -> list[RawPosting]:
        return [good_posting]

    async def dispatch(client: object, company_slug: str) -> list[RawPosting]:
        if company_slug == "bad":
            return await failing_fetch(client, company_slug)
        return await working_fetch(client, company_slug)

    monkeypatch.setattr(discovery_module, "fetch_greenhouse_postings", dispatch)

    async with session_factory() as db:
        user = await _make_user(db)
        db.add(JobBoardFeed(user_id=user.id, board="greenhouse", company_slug="bad"))
        db.add(JobBoardFeed(user_id=user.id, board="greenhouse", company_slug="good"))
        await db.commit()

    await run_scheduled_feed_polls()  # must not raise despite the first feed failing

    async with session_factory() as db:
        postings = (
            (await db.execute(select(JobPosting).where(JobPosting.user_id == user.id)))
            .scalars()
            .all()
        )
        failed_entry = (
            await db.execute(select(AuditLog).where(AuditLog.action == "career.feed.poll_failed"))
        ).scalar_one()
    assert len(postings) == 1  # the good feed still ran
    assert failed_entry.evidence["trigger"] == "scheduled"


# --- run_scheduled_digest_generation -----------------------------------------------------------


async def test_scheduled_digest_generation_creates_a_digest_per_user(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as db:
        user = await _make_user(db)
        await db.commit()

    await run_scheduled_digest_generation()

    async with session_factory() as db:
        digest = (
            await db.execute(select(WeeklyDigest).where(WeeklyDigest.user_id == user.id))
        ).scalar_one()
        entry = (
            await db.execute(
                select(AuditLog).where(AuditLog.action == "reporting.digest.generated")
            )
        ).scalar_one()
    assert digest.data["period"]["end"] is not None
    assert entry.evidence["trigger"] == "scheduled"


# --- run_scheduled_gmail_syncs (Group B) ------------------------------------------------------


async def _gmail_connection(
    session_factory: async_sessionmaker[AsyncSession], **overrides: object
) -> GmailConnection:
    async with session_factory() as db:
        user = await _make_user(db)
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
        await db.commit()
        return connection


async def test_scheduled_gmail_sync_runs_for_every_connected_connection(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_list_message_ids(client, access_token, *, query=None, page_token=None):  # type: ignore[no-untyped-def]
        return [], None

    async def fake_get_profile(client, access_token):  # type: ignore[no-untyped-def]
        return {"historyId": "1"}

    monkeypatch.setattr(gmail_sync, "list_message_ids", fake_list_message_ids)
    monkeypatch.setattr(gmail_sync, "get_profile", fake_get_profile)
    connection = await _gmail_connection(session_factory)

    await run_scheduled_gmail_syncs()

    async with session_factory() as db:
        run = (
            await db.execute(
                select(GmailSyncRun).where(GmailSyncRun.connection_id == connection.id)
            )
        ).scalar_one()
    assert run.status == "completed"
    assert run.sync_type == "backfill"  # no last_history_id yet


async def test_scheduled_gmail_sync_skips_a_disconnected_connection(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    connection = await _gmail_connection(
        session_factory, status="disconnected", access_token_encrypted=None
    )

    await run_scheduled_gmail_syncs()

    async with session_factory() as db:
        runs = (
            (
                await db.execute(
                    select(GmailSyncRun).where(GmailSyncRun.connection_id == connection.id)
                )
            )
            .scalars()
            .all()
        )
    assert runs == []


async def test_scheduled_gmail_sync_skips_a_connection_with_an_active_run(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def should_not_be_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("run_sync should not have been called")

    monkeypatch.setattr(gmail_sync, "run_sync", should_not_be_called)
    connection = await _gmail_connection(session_factory)
    async with session_factory() as db:
        db.add(
            GmailSyncRun(
                connection_id=connection.id,
                sync_type="incremental",
                status="running",
                started_at=datetime.now(UTC),
            )
        )
        await db.commit()

    await run_scheduled_gmail_syncs()  # must not raise via should_not_be_called


# --- run_scheduled_calendar_syncs (Group B) ---------------------------------------------------


async def _calendar_connection(
    session_factory: async_sessionmaker[AsyncSession], **overrides: object
) -> CalendarConnection:
    async with session_factory() as db:
        user = await _make_user(db)
        fields: dict[str, object] = {
            "user_id": user.id,
            "google_email": "aziz@gmail.com",
            "access_token_encrypted": encrypt_token("access-token"),
            "refresh_token_encrypted": encrypt_token("refresh-token"),
            "token_expires_at": datetime.now(UTC) + timedelta(hours=1),
            "granted_scopes": calendar_oauth.CALENDAR_READONLY_SCOPE,
            "status": "connected",
            **overrides,
        }
        connection = CalendarConnection(**fields)  # type: ignore[arg-type]
        db.add(connection)
        await db.commit()
        return connection


async def test_scheduled_calendar_sync_runs_for_every_connected_connection(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeCalendar()
    fake.events_page([])
    monkeypatch.setattr(calendar_sync.httpx, "AsyncClient", fake.client_factory())
    connection = await _calendar_connection(session_factory)

    await run_scheduled_calendar_syncs()

    async with session_factory() as db:
        run = (
            await db.execute(
                select(CalendarSyncRun).where(CalendarSyncRun.connection_id == connection.id)
            )
        ).scalar_one()
        entry = (
            await db.execute(select(AuditLog).where(AuditLog.action == "calendar.synced"))
        ).scalar_one()
    assert run.status == "completed"
    assert entry.evidence["trigger"] == "scheduled"


async def test_scheduled_calendar_sync_skips_a_disconnected_connection(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeCalendar()
    monkeypatch.setattr(calendar_sync.httpx, "AsyncClient", fake.client_factory())
    await _calendar_connection(session_factory, status="disconnected", access_token_encrypted=None)

    await run_scheduled_calendar_syncs()

    assert fake.requests == []


async def test_scheduled_calendar_sync_skips_a_connection_with_an_active_run(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeCalendar()
    monkeypatch.setattr(calendar_sync.httpx, "AsyncClient", fake.client_factory())
    connection = await _calendar_connection(session_factory)
    async with session_factory() as db:
        db.add(
            CalendarSyncRun(
                connection_id=connection.id, status="running", started_at=datetime.now(UTC)
            )
        )
        await db.commit()

    await run_scheduled_calendar_syncs()

    assert fake.requests == []
