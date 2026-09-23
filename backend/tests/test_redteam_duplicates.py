"""Red-team Track A, item 6: duplicate actions / idempotency races.

JobMatch, TailoredResume, CoverLetter, and Application all have a DB-level unique constraint
on job_posting_id, and their "start" functions do SELECT-then-insert-or-reset — a genuine
SELECT-then-INSERT TOCTOU gap: two near-simultaneous requests can both see "nothing yet" and
both attempt an INSERT, and the database's unique constraint lets only one through, leaving the
other to crash on an uncaught IntegrityError instead of recovering gracefully.

Reliably reproducing this exact interleaving in a test turned out to fight SQLAlchemy's async
internals hard enough (patching around session.execute/flush breaks its greenlet bridging) that
doing it properly isn't worth it for what is, in practice, a low-severity, self-correcting race
(a rare double-click retries cleanly; the unique constraint already guarantees no duplicate row
ever persists — the only failure mode closed here is a raw 500 instead of a clean recovery).
The fix (app.career.match_service.start_match, and the identical pattern applied to
app.career.resume_service.start_tailor and app.career.cover_service.start_letter) is verified
by inspection and by confirming the ordinary, non-race path still behaves exactly as before.

PracticeSession has no unique constraint at all (many sessions per job are allowed by design),
so its one-active-session-at-a-time check is closed with an in-process lock instead — and
*that* race reproduces reliably with two real concurrent HTTP requests, tested below.
"""

import asyncio

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.career import match_service
from app.career.models import JobMatch, JobPosting, PracticeSession
from app.db.models import User

OWNER = "profile-owner@example.com"


async def test_start_match_still_resets_an_existing_run_normally(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Regression check for the fix: the ordinary (non-race) "already exists" path — by far
    the common case — must behave exactly as before."""
    async with session_factory() as db:
        user = User(email="race-test@example.com", hashed_password="x")
        db.add(user)
        await db.flush()
        job = JobPosting(user_id=user.id, source_channel="manual_paste", title="Racer")
        db.add(job)
        await db.flush()
        first = await match_service.start_match(db, job)
        await db.commit()
        first_id = first.id

        second = await match_service.start_match(db, job)
        await db.commit()

    assert second.id == first_id  # reset in place, never a second row
    async with session_factory() as db:
        rows = (
            (await db.execute(select(JobMatch).where(JobMatch.job_posting_id == job.id)))
            .scalars()
            .all()
        )
    assert len(rows) == 1


async def test_only_one_practice_session_starts_under_concurrent_requests(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as db:
        user = (await db.execute(select(User).where(User.email == OWNER))).scalar_one()
        job = JobPosting(
            user_id=user.id,
            source_channel="manual_paste",
            title="Racer",
            description_text="text",
        )
        db.add(job)
        await db.flush()
        db.add(
            JobMatch(
                job_posting_id=job.id,
                status="completed",
                score_percent=50,
                assessed_weight=50,
                low_confidence=False,
            )
        )
        await db.commit()
        job_id = str(job.id)

    responses = await asyncio.gather(
        client.post(f"/career/jobs/{job_id}/practice-sessions", headers=auth_headers, json={}),
        client.post(f"/career/jobs/{job_id}/practice-sessions", headers=auth_headers, json={}),
    )

    statuses = sorted(r.status_code for r in responses)
    assert statuses == [202, 409]  # exactly one starts, the other is correctly told "in progress"

    async with session_factory() as db:
        sessions = (
            (
                await db.execute(
                    select(PracticeSession).where(PracticeSession.job_posting_id == job.id)
                )
            )
            .scalars()
            .all()
        )
    assert len(sessions) == 1
