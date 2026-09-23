"""Phase 11: a background scheduler for actions that were already Green (no confirmation
needed) but, until now, still needed a human to click a button to start each run.

Group A (GitHub sync, job-board feed polling, weekly digest generation): read-only or pure
aggregation, never write anywhere outside the user's own local data, fully reversible.

Group B (Gmail sync, Calendar sync): added in a later, separate decision because these two
connections' OAuth tokens have real reauth fragility (Gmail's refresh token expires roughly
weekly while the Google OAuth consent screen stays in "Testing" status) — losing the
click-time feedback loop meant a silent reauth failure needed its own answer. That answer is
two-part: the weekly digest already surfaces `connections_needing_reauth` (now generated on
its own schedule per Group A), and a persistent app-shell banner (frontend) now shows a
needs_reauth connection on every page load, not just on the dedicated integration page —
closing the gap from "next weekly digest" to "next time the app is open at all."

Every job here calls the exact same service-layer function the corresponding manual endpoint
calls — same audit trail, same error handling, same status tracking on the underlying run/feed
row. The only new thing is the `trigger="scheduled"` tag threaded into that action's own audit
evidence (where one exists — Gmail sync doesn't audit-log at all today, Group A/B didn't add
that), so /audit/logs can distinguish an autonomous run from a manual one.
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.calendar import sync as calendar_sync
from app.calendar.models import CalendarConnection, CalendarSyncRun
from app.career import discovery as career_discovery
from app.career.models import JobBoardFeed
from app.config import Settings
from app.db import base as db_base
from app.db.models import User
from app.github import sync as github_sync
from app.github.models import GithubConnection, GithubSyncRun
from app.gmail import sync as gmail_sync
from app.gmail.models import GmailConnection, GmailSyncRun
from app.logging import get_logger
from app.reporting.service import create_digest

logger = get_logger(__name__)

GITHUB_SYNC_JOB_ID = "scheduled_github_sync"
JOB_FEED_POLL_JOB_ID = "scheduled_job_feed_poll"
DIGEST_GENERATION_JOB_ID = "scheduled_digest_generation"
GMAIL_SYNC_JOB_ID = "scheduled_gmail_sync"
CALENDAR_SYNC_JOB_ID = "scheduled_calendar_sync"


async def run_scheduled_github_syncs() -> None:
    """Mirrors app.github.sync_router.start_sync: skip a connection that isn't connected, or
    that already has an active run (same is_active check the manual endpoint uses)."""
    async with db_base.async_session_factory() as db:
        connections = (
            (
                await db.execute(
                    select(GithubConnection).where(GithubConnection.status == "connected")
                )
            )
            .scalars()
            .all()
        )
        for connection in connections:
            recent = (
                (
                    await db.execute(
                        select(GithubSyncRun)
                        .where(GithubSyncRun.connection_id == connection.id)
                        .order_by(GithubSyncRun.started_at.desc())
                        .limit(5)
                    )
                )
                .scalars()
                .all()
            )
            if any(github_sync.is_active(run) for run in recent):
                logger.info(
                    "scheduled_github_sync_skipped_already_running",
                    connection_id=str(connection.id),
                )
                continue
            run = await github_sync.start_run(db, connection.id)
            await github_sync.run_sync(db, run.id, trigger="scheduled")


async def run_scheduled_feed_polls() -> None:
    """Mirrors app.career.router._poll_feed_in_background for every feed, not just one."""
    async with db_base.async_session_factory() as db:
        feeds = (await db.execute(select(JobBoardFeed))).scalars().all()
        for feed in feeds:
            try:
                await career_discovery.poll_company_feed(db, feed, trigger="scheduled")
            except career_discovery.DiscoveryError:
                pass  # already recorded on the feed and in the audit log
            await db.commit()


async def run_scheduled_digest_generation() -> None:
    """One digest per user who exists — in practice, this single-user app's one owner."""
    async with db_base.async_session_factory() as db:
        user_ids = (await db.execute(select(User.id))).scalars().all()
        for user_id in user_ids:
            await create_digest(db, user_id, trigger="scheduled")
            await db.commit()


async def run_scheduled_gmail_syncs() -> None:
    """Mirrors app.gmail.router.start_sync's own-connection lookup and run creation. Gmail's
    manual endpoint doesn't guard against an already-active run (a pre-existing gap, not
    introduced here) — added here anyway since an unattended scheduler repeating every 6h is a
    different risk profile than a human clicking a button once."""
    async with db_base.async_session_factory() as db:
        connections = (
            (
                await db.execute(
                    select(GmailConnection).where(GmailConnection.status == "connected")
                )
            )
            .scalars()
            .all()
        )
        for connection in connections:
            recent = (
                (
                    await db.execute(
                        select(GmailSyncRun)
                        .where(GmailSyncRun.connection_id == connection.id)
                        .order_by(GmailSyncRun.started_at.desc())
                        .limit(5)
                    )
                )
                .scalars()
                .all()
            )
            if any(
                run.status in ("pending", "running") and not gmail_sync.is_stalled(run)
                for run in recent
            ):
                logger.info(
                    "scheduled_gmail_sync_skipped_already_running",
                    connection_id=str(connection.id),
                )
                continue
            sync_type = "backfill" if connection.last_history_id is None else "incremental"
            run = GmailSyncRun(connection_id=connection.id, sync_type=sync_type, status="pending")
            db.add(run)
            await db.commit()
            await db.refresh(run)
            await gmail_sync.run_sync(db, run.id)


async def run_scheduled_calendar_syncs() -> None:
    """Mirrors app.calendar.sync_router.start_sync: skip a connection that isn't connected, or
    that already has an active run (same is_active check the manual endpoint uses)."""
    async with db_base.async_session_factory() as db:
        connections = (
            (
                await db.execute(
                    select(CalendarConnection).where(CalendarConnection.status == "connected")
                )
            )
            .scalars()
            .all()
        )
        for connection in connections:
            recent = (
                (
                    await db.execute(
                        select(CalendarSyncRun)
                        .where(CalendarSyncRun.connection_id == connection.id)
                        .order_by(CalendarSyncRun.started_at.desc())
                        .limit(5)
                    )
                )
                .scalars()
                .all()
            )
            if any(calendar_sync.is_active(run) for run in recent):
                logger.info(
                    "scheduled_calendar_sync_skipped_already_running",
                    connection_id=str(connection.id),
                )
                continue
            run = await calendar_sync.start_run(db, connection.id)
            await calendar_sync.run_sync(db, run.id, trigger="scheduled")


def build_scheduler(settings: Settings) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_scheduled_github_syncs,
        "interval",
        hours=settings.github_sync_interval_hours,
        id=GITHUB_SYNC_JOB_ID,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        run_scheduled_feed_polls,
        "interval",
        hours=settings.job_feed_poll_interval_hours,
        id=JOB_FEED_POLL_JOB_ID,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        run_scheduled_digest_generation,
        "interval",
        days=settings.digest_generation_interval_days,
        id=DIGEST_GENERATION_JOB_ID,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        run_scheduled_gmail_syncs,
        "interval",
        hours=settings.gmail_sync_interval_hours,
        id=GMAIL_SYNC_JOB_ID,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        run_scheduled_calendar_syncs,
        "interval",
        hours=settings.calendar_sync_interval_hours,
        id=CALENDAR_SYNC_JOB_ID,
        max_instances=1,
        coalesce=True,
    )
    return scheduler
