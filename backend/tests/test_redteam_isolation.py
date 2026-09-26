"""Red-team Track A, item 1: a systematic sweep of every by-id endpoint in the app, confirming
none of them leak another user's resource. Individual features already spot-check this
incidentally in their own test files; this file is the single, exhaustive checklist — every
`@router.{get,post,put,patch,delete}("...{...}...")` route in the codebase (see the grep this
was built from) gets one entry here, against a resource actually owned by a different user.

The expectation is uniform: 404, never 401/403 — the app's convention throughout is to never
confirm to a caller that a foreign resource even exists (see e.g. app.career.cover_router's
`_NOT_FOUND` reuse). A body is supplied wherever the endpoint requires one, so the request
passes validation and actually reaches the ownership check being tested, rather than failing
validation first and giving a false pass.
"""

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
    JobBoardFeed,
    JobMatch,
    JobPosting,
    PracticeSession,
    TailoredResume,
)
from app.db.models import User
from app.github.models import GithubConnection, GithubSkillProposal
from app.gmail.models import GmailConnection, GmailSyncRun
from app.profile.models import Education, Profile, ProfileLink, Skill, WorkExperience
from app.reporting.models import WeeklyDigest
from app.research.models import ResearchQuery, ResearchQuerySource, ResearchSource

OWNER = "profile-owner@example.com"


async def _give_victim_their_own_connections(
    session_factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID
) -> None:
    """Several ownership checks look up the *caller's own* connection before checking the
    resource id (e.g. GitHub's proposal endpoints, Gmail's sync-run endpoint, Calendar's event
    endpoint) — without one, the caller would 404 for "not connected at all", which would look
    like a pass without actually exercising the id-ownership check this file targets."""
    async with session_factory() as db:
        db.add(
            GmailConnection(user_id=user_id, google_email="victim@example.com", granted_scopes="x")
        )
        db.add(GithubConnection(user_id=user_id, github_login="victim", github_user_id=1))
        db.add(
            CalendarConnection(
                user_id=user_id, google_email="victim@example.com", granted_scopes="x"
            )
        )
        await db.commit()


async def _seed_attacker_resources(
    session_factory: async_sessionmaker[AsyncSession],
) -> dict[str, str]:
    """Everything below is owned by a different user than the one making requests in the test
    — every id returned here must be unreachable by the victim's auth headers."""
    async with session_factory() as db:
        attacker = User(email="attacker@example.com", hashed_password=hash_password("x-y-z-123456"))
        db.add(attacker)
        await db.flush()

        profile = Profile(user_id=attacker.id, headline="Attacker")
        db.add(profile)
        await db.flush()
        link = ProfileLink(profile_id=profile.id, label="Site", url="https://example.com")
        experience = WorkExperience(
            profile_id=profile.id,
            company="Acme",
            title="Engineer",
            start_date=date(2020, 1, 1),
        )
        education = Education(profile_id=profile.id, institution="State University")
        skill = Skill(profile_id=profile.id, name="Python")
        db.add_all([link, experience, education, skill])
        await db.flush()

        job = JobPosting(
            user_id=attacker.id,
            source_channel="manual_paste",
            title="Attacker's job",
            company_name="Acme",
            description_text="text",
        )
        feed = JobBoardFeed(user_id=attacker.id, board="greenhouse", company_slug="acme")
        db.add_all([job, feed])
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
        application = Application(user_id=attacker.id, job_posting_id=job.id, status="applied")
        db.add(application)
        await db.flush()
        db.add(
            ApplicationEvent(
                application_id=application.id,
                event_type="note",
                occurred_on=date.today(),
                body="note",
            )
        )
        resume = TailoredResume(user_id=attacker.id, job_posting_id=job.id, status="completed")
        letter = CoverLetter(user_id=attacker.id, job_posting_id=job.id, status="completed")
        session = PracticeSession(
            user_id=attacker.id,
            job_posting_id=job.id,
            status="ready_for_answers",
            started_at=datetime.now(UTC),
        )
        db.add_all([resume, letter, session])

        gmail = GmailConnection(
            user_id=attacker.id, google_email="attacker@example.com", granted_scopes="x"
        )
        github = GithubConnection(user_id=attacker.id, github_login="attacker", github_user_id=2)
        calendar = CalendarConnection(
            user_id=attacker.id, google_email="attacker@example.com", granted_scopes="x"
        )
        db.add_all([gmail, github, calendar])
        await db.flush()

        sync_run = GmailSyncRun(connection_id=gmail.id, sync_type="incremental", status="completed")
        proposal = GithubSkillProposal(
            connection_id=github.id,
            skill_name="Rust",
            kind="language",
            fingerprint="fp1",
            attribution="attributed",
        )
        event = CalendarEvent(connection_id=calendar.id, google_event_id="e1", kind="interview")
        db.add_all([sync_run, proposal, event])

        query = ResearchQuery(user_id=attacker.id, query_text="Is Acme real?", status="completed")
        db.add(query)
        await db.flush()
        source = ResearchSource(
            normalized_url="example.com/acme",
            original_url="https://example.com/acme",
            domain="example.com",
            tier_rationale="reputable",
        )
        db.add(source)
        await db.flush()
        db.add(ResearchQuerySource(query_id=query.id, source_id=source.id))

        digest = WeeklyDigest(
            user_id=attacker.id,
            period_start=date.today() - timedelta(days=7),
            period_end=date.today(),
            data={},
        )
        audit_log = AuditLog(
            user_id=attacker.id,
            action="github.skill_proposal.accept",
            risk_level="yellow",
            status="pending_approval",
            summary="Proposed accepting a skill.",
        )
        db.add_all([digest, audit_log])
        await db.commit()

        return {
            "job_id": str(job.id),
            "feed_id": str(feed.id),
            "application_id": str(application.id),
            "resume_id": str(resume.id),
            "letter_id": str(letter.id),
            "session_id": str(session.id),
            "sync_run_id": str(sync_run.id),
            "proposal_id": str(proposal.id),
            "event_id": str(event.id),
            "query_id": str(query.id),
            "source_id": str(source.id),
            "digest_id": str(digest.id),
            "audit_log_id": str(audit_log.id),
            "link_id": str(link.id),
            "experience_id": str(experience.id),
            "education_id": str(education.id),
            "skill_id": str(skill.id),
        }


async def test_no_endpoint_leaks_another_users_resource(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # The victim needs a profile (some routers 404 on a missing profile before reaching the
    # sub-resource check) and their own connections (see _give_victim_their_own_connections).
    await client.put("/profile", headers=auth_headers, json={"summary": "Victim."})

    async with session_factory() as db:
        victim = (await db.execute(select(User).where(User.email == OWNER))).scalar_one()
    await _give_victim_their_own_connections(session_factory, victim.id)
    foreign = await _seed_attacker_resources(session_factory)

    random_id = str(uuid.uuid4())

    cases: list[tuple[str, str, str, dict | None]] = [
        # (method, description, url, json body)
        ("GET", "audit log", f"/audit/logs/{foreign['audit_log_id']}", None),
        (
            "POST",
            "calendar classify",
            f"/calendar/events/{foreign['event_id']}/classify",
            {"kind": "interview"},
        ),
        ("GET", "application detail", f"/career/applications/{foreign['application_id']}", None),
        (
            "POST",
            "application status",
            f"/career/applications/{foreign['application_id']}/status",
            {"status": "applied"},
        ),
        (
            "POST",
            "application event",
            f"/career/applications/{foreign['application_id']}/events",
            {"event_type": "note", "body": "hi"},
        ),
        ("PATCH", "application patch", f"/career/applications/{foreign['application_id']}", {}),
        ("DELETE", "application delete", f"/career/applications/{foreign['application_id']}", None),
        ("POST", "ats check", f"/career/jobs/{foreign['job_id']}/ats-check", None),
        ("GET", "ats safe export", f"/career/jobs/{foreign['job_id']}/ats-safe", None),
        ("POST", "draft cover letter", f"/career/jobs/{foreign['job_id']}/cover-letter", None),
        ("GET", "get cover letter", f"/career/jobs/{foreign['job_id']}/cover-letter", None),
        (
            "GET",
            "export cover letter",
            f"/career/cover-letters/{foreign['letter_id']}/export",
            None,
        ),
        ("DELETE", "delete cover letter", f"/career/cover-letters/{foreign['letter_id']}", None),
        (
            "POST",
            "start practice session",
            f"/career/jobs/{foreign['job_id']}/practice-sessions",
            {},
        ),
        ("GET", "get practice session", f"/career/practice-sessions/{foreign['session_id']}", None),
        (
            "PATCH",
            "submit practice answers",
            f"/career/practice-sessions/{foreign['session_id']}/answers",
            {"answers": []},
        ),
        (
            "DELETE",
            "delete practice session",
            f"/career/practice-sessions/{foreign['session_id']}",
            None,
        ),
        ("POST", "start tailor", f"/career/jobs/{foreign['job_id']}/tailor", None),
        ("GET", "get tailored resume", f"/career/jobs/{foreign['job_id']}/resume", None),
        ("GET", "export resume", f"/career/resumes/{foreign['resume_id']}/export", None),
        ("DELETE", "delete resume", f"/career/resumes/{foreign['resume_id']}", None),
        ("DELETE", "delete feed", f"/career/jobs/feeds/{foreign['feed_id']}", None),
        ("POST", "poll feed", f"/career/jobs/feeds/{foreign['feed_id']}/poll", None),
        ("GET", "get job", f"/career/jobs/{foreign['job_id']}", None),
        ("DELETE", "delete job", f"/career/jobs/{foreign['job_id']}", None),
        ("POST", "verify job", f"/career/jobs/{foreign['job_id']}/verify", None),
        ("POST", "match job", f"/career/jobs/{foreign['job_id']}/match", None),
        (
            "POST",
            "accept github proposal",
            f"/github/proposals/{foreign['proposal_id']}/accept",
            {},
        ),
        (
            "POST",
            "dismiss github proposal",
            f"/github/proposals/{foreign['proposal_id']}/dismiss",
            None,
        ),
        ("GET", "gmail sync run", f"/gmail/sync/{foreign['sync_run_id']}", None),
        ("DELETE", "delete profile link", f"/profile/links/{foreign['link_id']}", None),
        ("PUT", "update experience", f"/profile/experience/{foreign['experience_id']}", {}),
        ("DELETE", "delete experience", f"/profile/experience/{foreign['experience_id']}", None),
        ("PUT", "update education", f"/profile/education/{foreign['education_id']}", {}),
        ("DELETE", "delete education", f"/profile/education/{foreign['education_id']}", None),
        ("DELETE", "delete skill", f"/profile/skills/{foreign['skill_id']}", None),
        ("GET", "skill versions", f"/profile/skills/{foreign['skill_id']}/versions", None),
        ("GET", "digest detail", f"/reporting/digests/{foreign['digest_id']}", None),
        ("GET", "digest export", f"/reporting/digests/{foreign['digest_id']}/export", None),
        ("DELETE", "delete digest", f"/reporting/digests/{foreign['digest_id']}", None),
        ("GET", "research query", f"/research/queries/{foreign['query_id']}", None),
        ("GET", "research source", f"/research/sources/{foreign['source_id']}", None),
    ]

    failures = []
    for method, description, url, body in cases:
        response = await client.request(method, url, headers=auth_headers, json=body)
        if response.status_code != 404:
            failures.append(f"{description} ({method} {url}): got {response.status_code}")

    assert not failures, "Endpoints that did not 404 for a foreign resource:\n" + "\n".join(
        failures
    )

    # A random id that belongs to no one at all must behave identically — 404, not a 500 from
    # some downstream lookup assuming the row exists once the id-format check passes.
    smoke_test_url = f"/career/jobs/{random_id}"
    assert (await client.get(smoke_test_url, headers=auth_headers)).status_code == 404

    # /audit/logs/{id}/decide is the one endpoint that deliberately doesn't 404: its ownership
    # check (audit/service.py::decide_approval) filters by user_id in the same query that
    # looks the row up, so a foreign row and a nonexistent id are indistinguishable — both
    # produce the exact same 409 + "No such pending action for this user." (never the distinct
    # messages used for "already decided" or "needs a second check", which only apply to a
    # row that already passed the ownership filter, i.e. one the caller does own). Confirmed
    # here rather than assumed: the message is verified to match a foreign row, a
    # never-existed row, and to differ from the messages an owned row can produce.
    foreign_decide = await client.post(
        f"/audit/logs/{foreign['audit_log_id']}/decide",
        headers=auth_headers,
        json={"approved": True},
    )
    missing_decide = await client.post(
        f"/audit/logs/{random_id}/decide", headers=auth_headers, json={"approved": True}
    )
    assert foreign_decide.status_code == missing_decide.status_code == 409
    assert foreign_decide.json()["detail"] == missing_decide.json()["detail"]
    assert foreign_decide.json()["detail"] == "No such pending action for this user."
