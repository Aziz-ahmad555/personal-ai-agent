"""The weekly digest through the API. No LLM anywhere in this module, so no fake LLM is
needed here — every assertion is "did the plain aggregation count/list the rows I seeded",
across Career, Research, Gmail, Calendar, GitHub, and the cross-cutting 'needs attention'
signals this app already computes elsewhere (follow_up_state, profile_stamp staleness,
is_stalled, needs_reauth, pending approvals/proposals)."""

import uuid
from datetime import UTC, date, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.models import AuditLog
from app.auth.security import hash_password
from app.calendar.models import CalendarConnection, CalendarEvent
from app.career.models import (
    Application,
    ApplicationEvent,
    CoverLetter,
    JobFraudAssessment,
    JobMatch,
    JobPosting,
    PracticeQuestion,
    PracticeSession,
    TailoredResume,
)
from app.db.models import User
from app.github.models import GithubConnection, GithubSkillProposal
from app.gmail.models import GmailConnection
from app.reporting.models import WeeklyDigest
from app.research.models import ResearchClaim, ResearchQuery

OWNER = "profile-owner@example.com"


async def _owner_id(session_factory: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    async with session_factory() as db:
        return (await db.execute(select(User).where(User.email == OWNER))).scalar_one().id


async def _job(
    session_factory: async_sessionmaker[AsyncSession],
    user_id: uuid.UUID,
    *,
    discovered_at: datetime,
) -> uuid.UUID:
    async with session_factory() as db:
        job = JobPosting(
            user_id=user_id,
            source_channel="manual_paste",
            title="ML Engineer",
            company_name="Acme Corp",
            remote_type="remote",
            discovered_at=discovered_at,
        )
        db.add(job)
        await db.commit()
        return job.id


async def _generate(client: AsyncClient, headers: dict[str, str], **body: int) -> dict:
    response = await client.post("/reporting/digests", headers=headers, json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def test_digest_aggregates_this_weeks_career_and_research_activity(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await client.put("/profile", headers=auth_headers, json={"summary": "Engineer."})
    user_id = await _owner_id(session_factory)
    now = datetime.now(UTC)
    in_window = now - timedelta(days=2)

    async with session_factory() as db:
        job_in = JobPosting(
            user_id=user_id,
            source_channel="manual_paste",
            title="ML Engineer",
            company_name="Acme Corp",
            remote_type="remote",
            discovered_at=in_window,
        )
        job_out = JobPosting(
            user_id=user_id,
            source_channel="manual_paste",
            title="Old Role",
            company_name="Stale Inc",
            remote_type="remote",
            discovered_at=now - timedelta(days=20),
        )
        db.add_all([job_in, job_out])
        await db.flush()

        db.add(
            JobMatch(
                job_posting_id=job_in.id,
                status="completed",
                score_percent=75,
                assessed_weight=75,
                low_confidence=False,
                computed_at=in_window,
            )
        )
        db.add(
            JobFraudAssessment(
                job_posting_id=job_in.id, risk_level="high", risk_score=80, assessed_at=in_window
            )
        )
        application = Application(user_id=user_id, job_posting_id=job_in.id, status="applied")
        db.add(application)
        await db.flush()
        db.add(
            ApplicationEvent(
                application_id=application.id,
                event_type="status_change",
                from_status="applied",
                to_status="interviewing",
                occurred_on=in_window.date(),
                created_at=in_window,
            )
        )
        db.add(
            CoverLetter(
                user_id=user_id, job_posting_id=job_in.id, status="completed", created_at=in_window
            )
        )
        db.add(
            TailoredResume(
                user_id=user_id, job_posting_id=job_in.id, status="completed", created_at=in_window
            )
        )
        session = PracticeSession(
            user_id=user_id,
            job_posting_id=job_in.id,
            status="completed",
            started_at=in_window,
            created_at=in_window,
        )
        db.add(session)
        await db.flush()
        db.add_all(
            [
                PracticeQuestion(
                    session_id=session.id,
                    position=0,
                    text="Q1",
                    category="technical",
                    ref_type="posting_requirement",
                    ref_name="Python",
                    ref_excerpt="Python required",
                    answer_text="I use Python daily.",
                    verdict="addressed",
                    feedback_text="Good.",
                ),
                PracticeQuestion(
                    session_id=session.id,
                    position=1,
                    text="Q2",
                    category="behavioral",
                    ref_type="profile_skill",
                    ref_name="FastAPI",
                    ref_excerpt="Built APIs.",
                ),
            ]
        )

        query = ResearchQuery(
            user_id=user_id,
            query_text="Is Acme Corp real?",
            status="completed",
            created_at=in_window,
            completed_at=in_window,
        )
        db.add(query)
        await db.flush()
        db.add(
            ResearchClaim(
                query_id=query.id,
                claim_text="Acme Corp is headquartered in SF.",
                status="corroborated",
                confidence_score=90,
                confidence_rationale="Two independent sources.",
                created_at=in_window,
            )
        )
        await db.commit()

    digest = await _generate(client, auth_headers)

    career = digest["data"]["career"]
    assert career["jobs_discovered"]["count"] == 1
    assert career["jobs_discovered"]["items"][0]["title"] == "ML Engineer"
    assert career["matches_computed"]["count"] == 1
    assert career["matches_computed"]["items"][0]["score_percent"] == 75
    assert career["high_risk_postings"]["count"] == 1
    assert career["application_status_changes"]["count"] == 1
    assert career["application_status_changes"]["by_status"] == {"interviewing": 1}
    assert career["cover_letters_drafted"]["count"] == 1
    assert career["resumes_drafted"]["count"] == 1
    assert career["practice_sessions"]["count"] == 1
    assert career["practice_sessions"]["verdict_tally"] == {
        "addressed": 1,
        "partially_addressed": 0,
        "missed": 0,
        "unclear": 0,
        "unanswered": 1,
    }

    research = digest["data"]["research"]
    assert research["queries_run"]["count"] == 1
    assert research["queries_completed"]["count"] == 1
    assert research["claims_added"]["count"] == 1
    assert research["claims_added"]["by_status"] == {"corroborated": 1}


async def test_digest_surfaces_needs_attention_signals(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    user_id = await _owner_id(session_factory)
    now = datetime.now(UTC)

    overdue_job = await _job(session_factory, user_id, discovered_at=now)
    stale_job = await _job(session_factory, user_id, discovered_at=now)
    stalled_job = await _job(session_factory, user_id, discovered_at=now)

    async with session_factory() as db:
        db.add(
            Application(
                user_id=user_id,
                job_posting_id=overdue_job,
                status="applied",
                # UTC's date, not date.today()'s local one — the service computes "today"
                # as datetime.now(UTC).date() (see reporting/service.py), and the two
                # disagree for several hours a day in any timezone ahead of UTC (this
                # local machine included), which silently turned "overdue" into
                # "due_today" whenever a test happened to run in that window.
                next_action_on=now.date() - timedelta(days=1),
                next_action_text="Follow up with recruiter",
            )
        )
        db.add(
            JobMatch(
                job_posting_id=stale_job,
                status="completed",
                score_percent=50,
                assessed_weight=50,
                low_confidence=False,
                profile_stamp="a-stamp-that-will-never-match-the-current-profile",
            )
        )
        db.add(
            JobMatch(
                job_posting_id=stalled_job,
                status="running",
                assessed_weight=0,
                low_confidence=True,
                started_at=now - timedelta(minutes=20),
            )
        )
        gmail = GmailConnection(
            user_id=user_id,
            google_email="me@example.com",
            granted_scopes="x",
            status="needs_reauth",
        )
        db.add(gmail)
        github = GithubConnection(
            user_id=user_id, github_login="me", github_user_id=1, status="connected"
        )
        db.add(github)
        await db.flush()
        db.add(
            GithubSkillProposal(
                connection_id=github.id,
                skill_name="Python",
                kind="language",
                fingerprint="fp1",
                attribution="attributed",
                status="pending",
            )
        )
        db.add(
            AuditLog(
                user_id=user_id,
                action="github.skill_proposal.accept",
                risk_level="yellow",
                status="pending_approval",
                summary="Proposed accepting a GitHub-evidenced skill.",
            )
        )
        await db.commit()

    digest = await _generate(client, auth_headers)
    attention = digest["data"]["attention"]

    assert len(attention["follow_ups_overdue"]) == 1
    assert attention["follow_ups_overdue"][0]["next_action_text"] == "Follow up with recruiter"
    assert any(item["id"] == str(stale_job) for item in attention["stale_matches"])
    assert any(
        run["id"] == str(stalled_job) and run["kind"] == "match"
        for run in attention["stalled_runs"]
    )
    assert "gmail" in attention["connections_needing_reauth"]
    assert attention["pending_audit_approvals"]["count"] == 1
    assert attention["pending_skill_proposals"]["count"] == 1


async def test_digest_reports_disconnected_integrations_honestly(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    digest = await _generate(client, auth_headers)

    assert digest["data"]["gmail"] == {"connected": False}
    assert digest["data"]["github"] == {"connected": False}
    assert digest["data"]["calendar"] == {"connected": False}


async def test_digest_lists_upcoming_calendar_events_in_the_lookahead_window(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    user_id = await _owner_id(session_factory)
    now = datetime.now(UTC)

    async with session_factory() as db:
        connection = CalendarConnection(
            user_id=user_id, google_email="me@example.com", granted_scopes="x", status="connected"
        )
        db.add(connection)
        await db.flush()
        db.add_all(
            [
                CalendarEvent(
                    connection_id=connection.id,
                    google_event_id="e1",
                    summary="Interview with Acme",
                    kind="interview",
                    start_at=now + timedelta(days=3),
                    is_all_day=False,
                ),
                CalendarEvent(
                    connection_id=connection.id,
                    google_event_id="e2",
                    summary="Application deadline",
                    kind="deadline",
                    start_at=now + timedelta(days=5),
                    is_all_day=True,
                ),
                CalendarEvent(
                    connection_id=connection.id,
                    google_event_id="e3",
                    summary="Too far out",
                    kind="interview",
                    start_at=now + timedelta(days=30),
                    is_all_day=False,
                ),
            ]
        )
        await db.commit()

    digest = await _generate(client, auth_headers, lookahead_days=14)
    calendar = digest["data"]["calendar"]

    assert calendar["connected"] is True
    assert [e["summary"] for e in calendar["upcoming_interviews"]] == ["Interview with Acme"]
    assert [e["summary"] for e in calendar["upcoming_deadlines"]] == ["Application deadline"]


async def test_export_is_a_frozen_snapshot_and_looks_like_a_pdf(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    user_id = await _owner_id(session_factory)
    now = datetime.now(UTC)
    await _job(session_factory, user_id, discovered_at=now)

    digest = await _generate(client, auth_headers)
    assert digest["data"]["career"]["jobs_discovered"]["count"] == 1

    # A job discovered after the digest was generated must not change the stored snapshot.
    await _job(session_factory, user_id, discovered_at=now)
    refetched = await client.get(f"/reporting/digests/{digest['id']}", headers=auth_headers)
    assert refetched.json()["data"]["career"]["jobs_discovered"]["count"] == 1

    export = await client.get(f"/reporting/digests/{digest['id']}/export", headers=auth_headers)
    assert export.status_code == 200
    assert export.headers["content-type"] == "application/pdf"
    assert export.content.startswith(b"%PDF")


async def test_generate_validates_the_window_bounds(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    too_small = await client.post("/reporting/digests", headers=auth_headers, json={"days": 0})
    too_large = await client.post("/reporting/digests", headers=auth_headers, json={"days": 91})
    bad_lookahead = await client.post(
        "/reporting/digests", headers=auth_headers, json={"lookahead_days": 0}
    )

    assert too_small.status_code == 422
    assert too_large.status_code == 422
    assert bad_lookahead.status_code == 422


async def test_other_users_digests_are_invisible_and_delete_is_audited(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as db:
        other = User(
            email="other-digest@example.com", hashed_password=hash_password("x-y-z-123456")
        )
        db.add(other)
        await db.commit()
        foreign = WeeklyDigest(
            user_id=other.id,
            period_start=date.today() - timedelta(days=7),
            period_end=date.today(),
            data={
                "period": {},
                "career": {},
                "research": {},
                "gmail": {},
                "github": {},
                "calendar": {},
                "attention": {},
            },
        )
        db.add(foreign)
        await db.commit()
        foreign_id = str(foreign.id)

    assert (
        await client.get(f"/reporting/digests/{foreign_id}", headers=auth_headers)
    ).status_code == 404
    assert (
        await client.get(f"/reporting/digests/{foreign_id}/export", headers=auth_headers)
    ).status_code == 404
    assert (
        await client.delete(f"/reporting/digests/{foreign_id}", headers=auth_headers)
    ).status_code == 404

    digest = await _generate(client, auth_headers)
    listed = await client.get("/reporting/digests", headers=auth_headers)
    assert all(d["id"] != foreign_id for d in listed.json())

    delete = await client.delete(f"/reporting/digests/{digest['id']}", headers=auth_headers)
    assert delete.status_code == 204
    assert (
        await client.get(f"/reporting/digests/{digest['id']}", headers=auth_headers)
    ).status_code == 404

    async with session_factory() as db:
        actions = set((await db.execute(select(AuditLog.action))).scalars().all())
    assert {"reporting.digest.generated", "reporting.digest.deleted"} <= actions
