"""Phase 11, Group A: a background scheduler for three actions that were already Green
(no confirmation needed) but, until now, still needed a human to click a button to start each
run. All three are read-only-or-pure-aggregation, never write anywhere outside the user's own
local data, and are fully reversible (a bad run is just redone) — GitHub sync, job-board feed
polling, and weekly digest generation.

Deliberately excludes Gmail and Calendar sync: those connections' OAuth tokens have real
reauth fragility (Gmail's refresh token expires roughly weekly while the Google OAuth consent
screen stays in "Testing" status) that needs its own explicit decision about how a silent
failure gets surfaced — not bundled into this lower-risk group.

Every job here calls the exact same service-layer function the corresponding manual endpoint
calls — same audit trail, same error handling, same status tracking on the underlying run/feed
row. The only new thing is the `trigger="scheduled"` tag threaded into that action's own audit
evidence, so /audit/logs can distinguish an autonomous run from a manual one.
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.career import discovery as career_discovery
from app.career.models import JobBoardFeed
from app.config import Settings
from app.db import base as db_base
from app.db.models import User
from app.github import sync as github_sync
from app.github.models import GithubConnection, GithubSyncRun
from app.logging import get_logger
from app.reporting.service import create_digest

logger = get_logger(__name__)

GITHUB_SYNC_JOB_ID = "scheduled_github_sync"
JOB_FEED_POLL_JOB_ID = "scheduled_job_feed_poll"
DIGEST_GENERATION_JOB_ID = "scheduled_digest_generation"


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
    return scheduler
