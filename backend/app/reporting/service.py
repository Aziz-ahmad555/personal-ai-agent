"""Weekly digest aggregation. Every number here comes from a plain query or a reuse of a
signal already computed elsewhere in the app (profile_stamp staleness, follow_up_state,
is_stalled, connection status) — there is no LLM call anywhere in this module, per CLAUDE.md's
"no LLM for deterministic work" and the Phase 9 plan. A digest is generated synchronously and
frozen into a WeeklyDigest row; nothing here re-runs once stored.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditLog
from app.audit.service import log_action
from app.calendar import sync as calendar_sync
from app.calendar.models import CalendarConnection, CalendarEvent, CalendarSyncRun
from app.career import cover_service, match_service, practice_service, resume_service
from app.career.application_rules import follow_up_state
from app.career.models import (
    Application,
    CoverLetter,
    JobFraudAssessment,
    JobMatch,
    JobPosting,
    PracticeQuestion,
    PracticeSession,
    TailoredResume,
)
from app.career.models import ApplicationEvent as AppEvent
from app.db.models import User
from app.github import readiness_router as github_readiness
from app.github import sync as github_sync
from app.github.models import GithubConnection, GithubRepo, GithubSkillProposal, GithubSyncRun
from app.gmail import sync as gmail_sync
from app.gmail.models import EmailMessage, GmailConnection, GmailSyncRun
from app.reporting.models import WeeklyDigest
from app.research.models import ResearchClaim, ResearchQuery

# Item lists are capped so a long history doesn't produce an unbounded JSON blob; the `count`
# field alongside every list is always the true total, never capped.
_LIST_CAP = 10
DEFAULT_DAYS = 7
DEFAULT_LOOKAHEAD_DAYS = 14


def _aware(value: datetime) -> datetime:
    """SQLite (used in tests) doesn't round-trip timezone info the way Postgres does, so a
    value read back can come back naive — same idiom as app.career.cover_service._as_utc and
    app.calendar.sync._aware. Date-range filtering here is done in Python against values
    normalized this way, rather than pushed into SQL, for the same reason: a naive-vs-aware
    comparison at the SQL layer would behave differently across the two backends."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _in_range(value: datetime | None, start: datetime, end: datetime) -> bool:
    return value is not None and start <= _aware(value) <= end


def _job_ref(job: JobPosting) -> dict[str, Any]:
    return {"id": str(job.id), "title": job.title, "company_name": job.company_name}


async def build_digest(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    days: int = DEFAULT_DAYS,
    lookahead_days: int = DEFAULT_LOOKAHEAD_DAYS,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    period_start = now - timedelta(days=days)
    lookahead_end = now + timedelta(days=lookahead_days)

    gmail_connection = (
        await db.execute(select(GmailConnection).where(GmailConnection.user_id == user_id))
    ).scalar_one_or_none()
    calendar_connection = (
        await db.execute(select(CalendarConnection).where(CalendarConnection.user_id == user_id))
    ).scalar_one_or_none()
    github_connection = (
        await db.execute(select(GithubConnection).where(GithubConnection.user_id == user_id))
    ).scalar_one_or_none()

    # Computed once, reused by both the "this week" sections and the staleness checks in
    # "needs attention" — JobMatch uses a different stamp (match_service.load_profile_facts)
    # than TailoredResume/CoverLetter/PracticeSession (resume_service.load_base_resume(...)
    # .stamp()); the two are not comparable, so each artifact type is checked against its own.
    _, match_stamp = await match_service.load_profile_facts(db, user_id)
    base = await resume_service.load_base_resume(db, user_id)
    base_stamp = base.stamp()

    return {
        "period": {"start": period_start.date().isoformat(), "end": now.date().isoformat()},
        "generated_at": now.isoformat(),
        "career": await _career_section(db, user_id, period_start, now),
        "research": await _research_section(db, user_id, period_start, now),
        "gmail": await _gmail_section(db, gmail_connection, period_start, now),
        "github": await _github_section(db, github_connection, period_start, now),
        "calendar": await _calendar_section(db, calendar_connection, now, lookahead_end),
        "attention": await _attention_section(
            db,
            user_id,
            now,
            match_stamp=match_stamp,
            base_stamp=base_stamp,
            gmail_connection=gmail_connection,
            calendar_connection=calendar_connection,
            github_connection=github_connection,
        ),
    }


async def create_digest(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    days: int = DEFAULT_DAYS,
    lookahead_days: int = DEFAULT_LOOKAHEAD_DAYS,
    trigger: str = "manual",
) -> WeeklyDigest:
    """Builds a digest and stores it as a row, audit-logged — the one path both the manual
    /reporting/digests endpoint and the scheduled weekly job go through, so a scheduled digest
    is indistinguishable from a manually-requested one except for the `trigger` tag in its
    audit evidence."""
    data = await build_digest(db, user_id, days=days, lookahead_days=lookahead_days)
    period = data["period"]
    digest = WeeklyDigest(
        user_id=user_id,
        period_start=date.fromisoformat(period["start"]),
        period_end=date.fromisoformat(period["end"]),
        data=data,
    )
    db.add(digest)
    await db.flush()
    await log_action(
        db,
        user_id=user_id,
        action="reporting.digest.generated",
        risk_level="green",
        summary=f"Generated a weekly digest covering {period['start']} to {period['end']}.",
        evidence={"trigger": trigger},
        resource_type="weekly_digest",
        resource_id=digest.id,
    )
    return digest


async def _career_section(
    db: AsyncSession, user_id: uuid.UUID, start: datetime, end: datetime
) -> dict[str, Any]:
    all_jobs = (
        (await db.execute(select(JobPosting).where(JobPosting.user_id == user_id))).scalars().all()
    )
    jobs = sorted(
        (j for j in all_jobs if _in_range(j.discovered_at, start, end)),
        key=lambda j: j.discovered_at,
        reverse=True,
    )

    all_matches = (
        await db.execute(
            select(JobMatch, JobPosting)
            .join(JobPosting, JobMatch.job_posting_id == JobPosting.id)
            .where(JobPosting.user_id == user_id, JobMatch.status == "completed")
        )
    ).all()
    matches = sorted(
        (row for row in all_matches if _in_range(row[0].computed_at, start, end)),
        key=lambda row: row[0].computed_at,
        reverse=True,
    )

    all_frauds = (
        await db.execute(
            select(JobFraudAssessment, JobPosting)
            .join(JobPosting, JobFraudAssessment.job_posting_id == JobPosting.id)
            .where(JobPosting.user_id == user_id, JobFraudAssessment.risk_level == "high")
        )
    ).all()
    frauds = [row for row in all_frauds if _in_range(row[0].assessed_at, start, end)]

    all_status_changes = (
        await db.execute(
            select(AppEvent, JobPosting)
            .join(Application, AppEvent.application_id == Application.id)
            .join(JobPosting, Application.job_posting_id == JobPosting.id)
            .where(Application.user_id == user_id, AppEvent.event_type == "status_change")
        )
    ).all()
    status_changes = sorted(
        (row for row in all_status_changes if _in_range(row[0].created_at, start, end)),
        key=lambda row: row[0].created_at,
        reverse=True,
    )
    by_status: dict[str, int] = {}
    for event, _job in status_changes:
        if event.to_status:
            by_status[event.to_status] = by_status.get(event.to_status, 0) + 1

    all_letters = (
        await db.execute(
            select(CoverLetter, JobPosting)
            .join(JobPosting, CoverLetter.job_posting_id == JobPosting.id)
            .where(CoverLetter.user_id == user_id, CoverLetter.status == "completed")
        )
    ).all()
    letters = [row for row in all_letters if _in_range(row[0].created_at, start, end)]

    all_resumes = (
        await db.execute(
            select(TailoredResume, JobPosting)
            .join(JobPosting, TailoredResume.job_posting_id == JobPosting.id)
            .where(TailoredResume.user_id == user_id, TailoredResume.status == "completed")
        )
    ).all()
    resumes = [row for row in all_resumes if _in_range(row[0].created_at, start, end)]

    all_sessions = (
        await db.execute(
            select(PracticeSession, JobPosting)
            .join(JobPosting, PracticeSession.job_posting_id == JobPosting.id)
            .where(PracticeSession.user_id == user_id)
        )
    ).all()
    sessions = [row for row in all_sessions if _in_range(row[0].created_at, start, end)]
    verdict_tally = {
        "addressed": 0,
        "partially_addressed": 0,
        "missed": 0,
        "unclear": 0,
        "unanswered": 0,
    }
    session_ids = [s.id for s, _job in sessions]
    if session_ids:
        questions = (
            (
                await db.execute(
                    select(PracticeQuestion).where(PracticeQuestion.session_id.in_(session_ids))
                )
            )
            .scalars()
            .all()
        )
        for question in questions:
            if not (question.answer_text or "").strip():
                verdict_tally["unanswered"] += 1
            elif question.verdict in verdict_tally:
                verdict_tally[question.verdict] += 1

    return {
        "jobs_discovered": {"count": len(jobs), "items": [_job_ref(j) for j in jobs[:_LIST_CAP]]},
        "matches_computed": {
            "count": len(matches),
            "items": [
                {
                    **_job_ref(job),
                    "score_percent": m.score_percent,
                    "low_confidence": m.low_confidence,
                }
                for m, job in matches[:_LIST_CAP]
            ],
        },
        "high_risk_postings": {
            "count": len(frauds),
            "items": [_job_ref(job) for _fraud, job in frauds[:_LIST_CAP]],
        },
        "application_status_changes": {
            "count": len(status_changes),
            "by_status": by_status,
            "items": [
                {**_job_ref(job), "from_status": e.from_status, "to_status": e.to_status}
                for e, job in status_changes[:_LIST_CAP]
            ],
        },
        "cover_letters_drafted": {
            "count": len(letters),
            "items": [_job_ref(job) for _letter, job in letters[:_LIST_CAP]],
        },
        "resumes_drafted": {
            "count": len(resumes),
            "items": [_job_ref(job) for _resume, job in resumes[:_LIST_CAP]],
        },
        "practice_sessions": {
            "count": len(sessions),
            "verdict_tally": verdict_tally,
            "items": [_job_ref(job) for _session, job in sessions[:_LIST_CAP]],
        },
    }


async def _research_section(
    db: AsyncSession, user_id: uuid.UUID, start: datetime, end: datetime
) -> dict[str, Any]:
    all_queries = (
        (await db.execute(select(ResearchQuery).where(ResearchQuery.user_id == user_id)))
        .scalars()
        .all()
    )
    queries = [q for q in all_queries if _in_range(q.created_at, start, end)]
    completed = [
        q for q in queries if q.status == "completed" and _in_range(q.completed_at, start, end)
    ]

    all_claims = (
        (
            await db.execute(
                select(ResearchClaim)
                .join(ResearchQuery, ResearchClaim.query_id == ResearchQuery.id)
                .where(ResearchQuery.user_id == user_id)
            )
        )
        .scalars()
        .all()
    )
    claims = [c for c in all_claims if _in_range(c.created_at, start, end)]
    by_status: dict[str, int] = {}
    for claim in claims:
        by_status[claim.status] = by_status.get(claim.status, 0) + 1

    return {
        "queries_run": {
            "count": len(queries),
            "items": [
                {"id": str(q.id), "query_text": q.query_text[:200], "status": q.status}
                for q in queries[:_LIST_CAP]
            ],
        },
        "queries_completed": {"count": len(completed)},
        "claims_added": {"count": len(claims), "by_status": by_status},
    }


async def _gmail_section(
    db: AsyncSession, connection: GmailConnection | None, start: datetime, end: datetime
) -> dict[str, Any]:
    if connection is None:
        return {"connected": False}
    # Date-range and label-membership (a JSON array column) filtering both happen in Python:
    # the former for the naive/aware reason _in_range exists, the latter because label
    # membership isn't a portable SQL predicate across SQLite (tests) and Postgres (prod).
    rows = (
        (
            await db.execute(
                select(EmailMessage.fetched_at, EmailMessage.label_ids).where(
                    EmailMessage.connection_id == connection.id
                )
            )
        )
        .tuples()
        .all()
    )
    messages_synced = sum(1 for fetched_at, _labels in rows if _in_range(fetched_at, start, end))
    unread = sum(1 for _fetched_at, labels in rows if "UNREAD" in (labels or []))
    return {
        "connected": True,
        "status": connection.status,
        "messages_synced": {"count": messages_synced},
        "unread_count": unread,
    }


async def _github_section(
    db: AsyncSession, connection: GithubConnection | None, start: datetime, end: datetime
) -> dict[str, Any]:
    if connection is None:
        return {"connected": False}
    synced_ats = (
        (
            await db.execute(
                select(GithubRepo.synced_at).where(GithubRepo.connection_id == connection.id)
            )
        )
        .scalars()
        .all()
    )
    repos_synced = sum(1 for value in synced_ats if _in_range(value, start, end))
    pending_proposals = (
        await db.execute(
            select(func.count())
            .select_from(GithubSkillProposal)
            .where(
                GithubSkillProposal.connection_id == connection.id,
                GithubSkillProposal.status == "pending",
            )
        )
    ).scalar_one()

    user = await db.get(User, connection.user_id)
    passed, total, synced = 0, 0, False
    if user is not None:
        review = await github_readiness._review(db, user)  # reuses the existing, tested scoring
        passed = sum(r.passed for r in review.repos) + sum(
            c.status == "pass" for c in review.profile
        )
        total = sum(len(r.checks) for r in review.repos) + len(review.profile)
        synced = review.synced

    return {
        "connected": True,
        "status": connection.status,
        "repos_synced": {"count": repos_synced},
        "pending_proposals": {"count": pending_proposals},
        # "As of now," not "changed this week" — readiness has no stored history to diff against.
        "readiness": {"passed": passed, "total": total, "synced": synced},
    }


async def _calendar_section(
    db: AsyncSession, connection: CalendarConnection | None, now: datetime, lookahead_end: datetime
) -> dict[str, Any]:
    if connection is None:
        return {"connected": False}
    all_rows = (
        await db.execute(
            select(CalendarEvent, JobPosting)
            .outerjoin(Application, CalendarEvent.application_id == Application.id)
            .outerjoin(JobPosting, Application.job_posting_id == JobPosting.id)
            .where(
                CalendarEvent.connection_id == connection.id,
                CalendarEvent.kind.in_(["interview", "deadline"]),
            )
        )
    ).all()
    rows = sorted(
        (row for row in all_rows if _in_range(row[0].start_at, now, lookahead_end)),
        key=lambda row: row[0].start_at,
    )

    interviews: list[dict[str, Any]] = []
    deadlines: list[dict[str, Any]] = []
    for event, job in rows:
        entry = {
            "summary": event.summary,
            "start_at": event.start_at.isoformat() if event.start_at else None,
            "is_all_day": event.is_all_day,
            "job": _job_ref(job) if job else None,
        }
        (interviews if event.kind == "interview" else deadlines).append(entry)

    return {
        "connected": True,
        "status": connection.status,
        "upcoming_interviews": interviews,
        "upcoming_deadlines": deadlines,
    }


async def _attention_section(
    db: AsyncSession,
    user_id: uuid.UUID,
    now: datetime,
    *,
    match_stamp: str,
    base_stamp: str,
    gmail_connection: GmailConnection | None,
    calendar_connection: CalendarConnection | None,
    github_connection: GithubConnection | None,
) -> dict[str, Any]:
    applications = (
        await db.execute(
            select(Application, JobPosting)
            .join(JobPosting, Application.job_posting_id == JobPosting.id)
            .where(Application.user_id == user_id)
        )
    ).all()
    overdue: list[dict[str, Any]] = []
    due_today: list[dict[str, Any]] = []
    for application, job in applications:
        state = follow_up_state(application.next_action_on, application.status, today=now.date())
        entry = {**_job_ref(job), "next_action_text": application.next_action_text}
        if state == "overdue":
            overdue.append(entry)
        elif state == "due_today":
            due_today.append(entry)

    matches = (
        await db.execute(
            select(JobMatch, JobPosting)
            .join(JobPosting, JobMatch.job_posting_id == JobPosting.id)
            .where(JobPosting.user_id == user_id)
        )
    ).all()
    resumes = (
        await db.execute(
            select(TailoredResume, JobPosting)
            .join(JobPosting, TailoredResume.job_posting_id == JobPosting.id)
            .where(TailoredResume.user_id == user_id)
        )
    ).all()
    letters = (
        await db.execute(
            select(CoverLetter, JobPosting)
            .join(JobPosting, CoverLetter.job_posting_id == JobPosting.id)
            .where(CoverLetter.user_id == user_id)
        )
    ).all()
    sessions = (
        await db.execute(
            select(PracticeSession, JobPosting)
            .join(JobPosting, PracticeSession.job_posting_id == JobPosting.id)
            .where(PracticeSession.user_id == user_id)
        )
    ).all()

    stale_matches = [
        _job_ref(job)
        for m, job in matches
        if m.status == "completed" and m.profile_stamp != match_stamp
    ]
    stale_resumes = [
        _job_ref(job)
        for r, job in resumes
        if r.status == "completed" and r.profile_stamp != base_stamp
    ]
    stale_cover_letters = [
        _job_ref(job)
        for letter, job in letters
        if letter.status == "completed" and letter.profile_stamp != base_stamp
    ]

    stalled_runs: list[dict[str, Any]] = []
    stalled_runs += [
        {**_job_ref(job), "kind": "match"}
        for m, job in matches
        if match_service.is_stalled(m, now=now)
    ]
    stalled_runs += [
        {**_job_ref(job), "kind": "resume"}
        for r, job in resumes
        if resume_service.is_stalled(r, now=now)
    ]
    stalled_runs += [
        {**_job_ref(job), "kind": "cover_letter"}
        for letter, job in letters
        if cover_service.is_stalled(letter, now=now)
    ]
    stalled_runs += [
        {**_job_ref(job), "kind": "practice_session"}
        for session, job in sessions
        if practice_service.is_stalled(session, now=now)
    ]

    if gmail_connection is not None:
        latest_gmail_run = (
            await db.execute(
                select(GmailSyncRun)
                .where(GmailSyncRun.connection_id == gmail_connection.id)
                .order_by(GmailSyncRun.started_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if latest_gmail_run is not None and gmail_sync.is_stalled(latest_gmail_run, now=now):
            stalled_runs.append({"kind": "sync", "integration": "gmail"})

    if calendar_connection is not None:
        latest_calendar_run = (
            await db.execute(
                select(CalendarSyncRun)
                .where(CalendarSyncRun.connection_id == calendar_connection.id)
                .order_by(CalendarSyncRun.started_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if latest_calendar_run is not None and calendar_sync.is_stalled(
            latest_calendar_run, now=now
        ):
            stalled_runs.append({"kind": "sync", "integration": "calendar"})

    if github_connection is not None:
        latest_github_run = (
            await db.execute(
                select(GithubSyncRun)
                .where(GithubSyncRun.connection_id == github_connection.id)
                .order_by(GithubSyncRun.started_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if latest_github_run is not None and github_sync.is_stalled(latest_github_run, now=now):
            stalled_runs.append({"kind": "sync", "integration": "github"})

    needs_reauth = [
        name
        for name, connection in (
            ("gmail", gmail_connection),
            ("calendar", calendar_connection),
            ("github", github_connection),
        )
        if connection is not None and connection.status == "needs_reauth"
    ]

    pending_approvals = (
        await db.execute(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.user_id == user_id, AuditLog.status == "pending_approval")
        )
    ).scalar_one()
    pending_skill_proposals = 0
    if github_connection is not None:
        pending_skill_proposals = (
            await db.execute(
                select(func.count())
                .select_from(GithubSkillProposal)
                .where(
                    GithubSkillProposal.connection_id == github_connection.id,
                    GithubSkillProposal.status == "pending",
                )
            )
        ).scalar_one()

    return {
        "follow_ups_overdue": overdue,
        "follow_ups_due_today": due_today,
        "stale_matches": stale_matches,
        "stale_resumes": stale_resumes,
        "stale_cover_letters": stale_cover_letters,
        "stalled_runs": stalled_runs,
        "connections_needing_reauth": needs_reauth,
        "pending_audit_approvals": {"count": pending_approvals},
        "pending_skill_proposals": {"count": pending_skill_proposals},
    }
