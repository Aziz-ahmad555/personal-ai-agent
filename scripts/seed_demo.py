"""Seeds (or re-seeds) the one demo account the public demo runs as.

Idempotent: deletes the demo user (DB-level ON DELETE CASCADE removes every row that hangs off
it — profile, connections, career data, research, audit) and rebuilds everything fresh, so this
is safe to run on a schedule (see docs/decisions.md for why that's an external cron invoking
this script, never the backend's own APScheduler — scripts/ imports from backend/, never the
reverse).

Deliberately does NOT drive the real LLM pipelines (verify_and_assess_job, run_match's requirement
extraction, run_tailor, run_letter, run_question_generation/run_feedback_generation) — those cost
real money and are non-deterministic, wrong things for a scheduled reset to depend on. Instead
this constructs the finished rows directly with the ORM, in the same shapes those pipelines
produce (see each model's own docstring in app/*/models.py). The one exception is
app.reporting.service.create_digest: it's plain, deterministic code that reads rows rather than
calling a model, so it's used for real here as the actual source of truth for the digest.

The persona (Alex Rivera, backend engineer, Python/PostgreSQL, Acme Corp) matches
evals/datasets/career_eval.json's fixture on purpose, so anyone comparing the demo against the
eval suite's own numbers is looking at the same person.

Run with the backend's own venv active (this project's `app` package is installed editable into
it, per backend/pyproject.toml):

    cd backend && python ../scripts/seed_demo.py
"""

import asyncio
import uuid
from datetime import UTC, date, datetime, timedelta

from app.audit.models import AuditLog
from app.auth.security import hash_password
from app.calendar.models import CalendarConnection, CalendarEvent, CalendarSyncRun
from app.career.models import (
    Application,
    ApplicationEvent,
    CoverLetter,
    CoverLetterParagraph,
    EmployerVerification,
    JobBoardFeed,
    JobFraudAssessment,
    JobMatch,
    JobPosting,
    PracticeQuestion,
    PracticeSession,
    ResumeChange,
    TailoredResume,
)
from app.career.resume_service import load_base_resume
from app.core.demo import DEMO_USER_EMAIL
from app.db.base import async_session_factory
from app.db.models import User
from app.github.models import GithubConnection, GithubRepo, GithubSkillProposal, GithubSyncRun
from app.gmail.models import EmailMessage, GmailConnection, GmailSyncRun
from app.profile.models import (
    Education,
    Preferences,
    Profile,
    ProfileLink,
    Skill,
    SkillVersion,
    WorkExperience,
)
from app.reporting.service import create_digest
from app.research.dedupe import normalize_url
from app.research.models import (
    ResearchClaim,
    ResearchClaimCitation,
    ResearchQuery,
    ResearchQuerySource,
    ResearchReport,
    ResearchSource,
)
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

NOW = datetime.now(UTC)


def days_ago(n: int) -> datetime:
    return NOW - timedelta(days=n)


async def _delete_existing_demo_user(db: AsyncSession) -> None:
    existing = (
        await db.execute(select(User).where(User.email == DEMO_USER_EMAIL))
    ).scalar_one_or_none()
    if existing is not None:
        await db.delete(existing)
        await db.flush()


async def _seed_user(db: AsyncSession) -> User:
    user = User(
        email=DEMO_USER_EMAIL,
        hashed_password=hash_password(uuid.uuid4().hex),  # unusable; /demo-login never checks it
        full_name="Alex Rivera",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _seed_profile(db: AsyncSession, user: User) -> Profile:
    profile = Profile(
        user_id=user.id,
        headline="Backend Engineer",
        summary=(
            "Backend engineer with 6 years building Python services on PostgreSQL, focused on "
            "reliability and clean API design. Recently picked up Kubernetes for a service "
            "migration and have been deepening that since."
        ),
        location="Austin, TX",
    )
    db.add(profile)
    await db.flush()

    db.add_all(
        [
            ProfileLink(
                profile_id=profile.id, label="GitHub", url="https://github.com/alex-rivera-demo"
            ),
            ProfileLink(
                profile_id=profile.id,
                label="LinkedIn",
                url="https://linkedin.com/in/alex-rivera-demo",
            ),
        ]
    )

    exp_acme = WorkExperience(
        profile_id=profile.id,
        company="Acme Corp",
        title="Senior Backend Engineer",
        location="Austin, TX (Remote)",
        start_date=date(2020, 3, 1),
        end_date=None,
        description=(
            "Built and maintained Python/PostgreSQL services handling millions of daily "
            "requests. Led migration of a monolith to a service-oriented architecture. "
            "Introduced Kubernetes for the payments service's rollout in 2024."
        ),
    )
    exp_bluewave = WorkExperience(
        profile_id=profile.id,
        company="Bluewave Software",
        title="Backend Engineer",
        location="Austin, TX",
        start_date=date(2018, 6, 1),
        end_date=date(2020, 2, 28),
        description="Built REST APIs in Python/Flask for a mid-size logistics platform.",
    )
    db.add_all([exp_acme, exp_bluewave])
    await db.flush()

    db.add(
        Education(
            profile_id=profile.id,
            institution="University of Texas at Austin",
            degree="B.S.",
            field="Computer Science",
            start_date=date(2014, 8, 1),
            end_date=date(2018, 5, 1),
        )
    )

    skills = [
        Skill(profile_id=profile.id, name="Python", category="language"),
        Skill(profile_id=profile.id, name="PostgreSQL", category="database"),
        Skill(profile_id=profile.id, name="Kubernetes", category="infrastructure"),
        Skill(profile_id=profile.id, name="Docker", category="infrastructure"),
        Skill(profile_id=profile.id, name="System Design", category="practice"),
    ]
    db.add_all(skills)
    await db.flush()
    by_name = {s.name: s for s in skills}

    db.add_all(
        [
            SkillVersion(
                skill_id=by_name["Python"].id,
                level="expert",
                evidence="6 years, Acme Corp and Bluewave Software",
                work_experience_id=exp_acme.id,
                asserted_at=days_ago(200),
            ),
            SkillVersion(
                skill_id=by_name["PostgreSQL"].id,
                level="advanced",
                evidence="6 years, Acme Corp and Bluewave Software",
                work_experience_id=exp_acme.id,
                asserted_at=days_ago(200),
            ),
            SkillVersion(
                skill_id=by_name["Kubernetes"].id,
                level="intermediate",
                evidence="Led the payments service's move onto Kubernetes in 2024.",
                work_experience_id=exp_acme.id,
                asserted_at=days_ago(90),
            ),
            SkillVersion(
                skill_id=by_name["Docker"].id,
                level="advanced",
                evidence="Containerized every service at Acme Corp prior to the Kubernetes move.",
                work_experience_id=exp_acme.id,
                asserted_at=days_ago(150),
            ),
            SkillVersion(
                skill_id=by_name["System Design"].id,
                level="advanced",
                evidence="Led the monolith-to-services migration end to end.",
                work_experience_id=exp_acme.id,
                asserted_at=days_ago(150),
            ),
        ]
    )

    db.add(
        Preferences(
            user_id=user.id,
            job_types=["full_time"],
            remote_preference="remote",
            locations=["Austin, TX", "Remote - US"],
            salary_min=140000,
            salary_max=190000,
            industries_include=["software", "developer tools"],
            industries_exclude=["defense"],
            deal_breakers="No fully on-site roles. No roles requiring travel over 25%.",
        )
    )
    await db.flush()
    return profile


async def _seed_gmail(db: AsyncSession, user: User) -> None:
    connection = GmailConnection(
        user_id=user.id,
        google_email="alex.rivera.demo@personal-ai-agent.example",
        granted_scopes="https://www.googleapis.com/auth/gmail.readonly",
        status="connected",
        last_synced_at=days_ago(1),
    )
    db.add(connection)
    await db.flush()

    thread_seed = [
        (
            "Interview invitation — Nimbus Data Systems",
            "recruiting@nimbusdatasystems.example",
            6,
            "Hi Alex, we'd love to schedule a first-round interview for the Senior Backend Engineer role.",
        ),
        (
            "Re: Interview invitation — Nimbus Data Systems",
            "alex.rivera.demo@personal-ai-agent.example",
            5,
            "Thanks, Tuesday at 2pm works well for me.",
        ),
        (
            "Your application to Lumen Cloud Works",
            "careers@lumencloudworks.example",
            10,
            "Thanks for applying to the Platform Engineer role. We'll be in touch within two weeks.",
        ),
        (
            "USAJOBS: Application Received",
            "donotreply@usajobs.gov.example",
            45,
            "Your application for Software Developer, Dept. of Veterans Affairs, has been received.",
        ),
        (
            "Weekly Python Newsletter",
            "newsletter@pythonweekly.example",
            2,
            "This week: async patterns, PEP 750, and more.",
        ),
        (
            "Weekly Python Newsletter",
            "newsletter@pythonweekly.example",
            9,
            "This week: structural pattern matching in practice.",
        ),
        ("Your GitHub digest", "noreply@github.example", 3, "Activity on repos you're watching."),
        (
            "Invoice from CloudHost",
            "billing@cloudhost.example",
            12,
            "Your monthly invoice is ready.",
        ),
        (
            "Re: Coffee next week?",
            "jordan.old-colleague@example.com",
            4,
            "Sure, Thursday works for me!",
        ),
        (
            "Interview follow-up — Nimbus Data Systems",
            "recruiting@nimbusdatasystems.example",
            3,
            "Great talking with you — next step is a technical screen with the team lead.",
        ),
        (
            "Password reset requested",
            "security@somesaas.example",
            20,
            "If this wasn't you, ignore this email.",
        ),
        ("Your order has shipped", "orders@retailer.example", 15, "Track your package."),
        (
            "Meetup: Austin Python",
            "events@austinpython.example",
            8,
            "Join us this Thursday for lightning talks.",
        ),
        (
            "Re: Your application to BrightPath Analytics",
            "talent@brightpathanalytics.example",
            25,
            "Thanks for your interest — we've decided to move forward with other candidates.",
        ),
        (
            "LinkedIn: You appeared in 12 searches this week",
            "notifications@linkedin.example",
            1,
            "",
        ),
        (
            "Reminder: renew your domain",
            "noreply@registrar.example",
            18,
            "alex-rivera-demo.dev expires soon.",
        ),
        (
            "Congrats on 5 years!",
            "hr@acmecorp.example",
            60,
            "Thank you for five years at Acme Corp.",
        ),
        ("Your PTO request was approved", "hr@acmecorp.example", 30, "Enjoy your time off."),
        (
            "Nimbus Data Systems — offer next steps",
            "recruiting@nimbusdatasystems.example",
            1,
            "We're finishing up reference checks and will follow up by end of week.",
        ),
        ("Statement ready", "statements@bankdemo.example", 5, "Your statement is ready to view."),
    ]
    for idx, (subject, sender, age_days, snippet) in enumerate(thread_seed):
        sent_at = days_ago(age_days)
        db.add(
            EmailMessage(
                connection_id=connection.id,
                gmail_message_id=f"demo-msg-{idx:03d}",
                thread_id=f"demo-thread-{idx // 2:03d}",
                subject=subject,
                from_address=sender,
                to_addresses=["alex.rivera.demo@personal-ai-agent.example"],
                date=sent_at,
                snippet=snippet,
                body_text=snippet,
                label_ids=["INBOX"] if idx % 4 else ["INBOX", "UNREAD"],
                fetched_at=days_ago(1),
            )
        )
    db.add(
        GmailSyncRun(
            connection_id=connection.id,
            sync_type="full",
            status="completed",
            messages_fetched=len(thread_seed),
            messages_stored=len(thread_seed),
            started_at=days_ago(1),
            completed_at=days_ago(1),
        )
    )


async def _seed_github(db: AsyncSession, user: User) -> None:
    connection = GithubConnection(
        user_id=user.id,
        github_login="alex-rivera-demo",
        github_user_id=90210001,
        status="connected",
        profile_facts={"name": "Alex Rivera", "location": "Austin, TX"},
    )
    db.add(connection)
    await db.flush()

    repos = [
        GithubRepo(
            connection_id=connection.id,
            github_repo_id=1001,
            name="order-service",
            full_name="alex-rivera-demo/order-service",
            html_url="https://github.com/alex-rivera-demo/order-service",
            description="Async FastAPI service backing order processing; Postgres + Redis.",
            primary_language="Python",
            topics=["fastapi", "postgresql", "kubernetes"],
            stars=14,
            forks=2,
            license_spdx="MIT",
            default_branch="main",
            details_fetched=True,
            languages={"Python": 82000, "Dockerfile": 900},
            root_files=["app", "tests", "Dockerfile", "k8s", "pyproject.toml"],
            authored_commits=340,
            first_commit_at=days_ago(700),
            last_commit_at=days_ago(20),
            created_at_gh=days_ago(700),
            pushed_at=days_ago(20),
        ),
        GithubRepo(
            connection_id=connection.id,
            github_repo_id=1002,
            name="pg-migration-toolkit",
            full_name="alex-rivera-demo/pg-migration-toolkit",
            html_url="https://github.com/alex-rivera-demo/pg-migration-toolkit",
            description="CLI helpers for zero-downtime PostgreSQL migrations.",
            primary_language="Python",
            topics=["postgresql", "cli"],
            stars=31,
            forks=5,
            license_spdx="Apache-2.0",
            default_branch="main",
            details_fetched=True,
            languages={"Python": 21000},
            root_files=["src", "tests", "README.md"],
            authored_commits=95,
            first_commit_at=days_ago(500),
            last_commit_at=days_ago(60),
            created_at_gh=days_ago(500),
            pushed_at=days_ago(60),
        ),
    ]
    db.add_all(repos)
    await db.flush()

    db.add(
        GithubSkillProposal(
            connection_id=connection.id,
            skill_name="Docker",
            kind="infrastructure",
            fingerprint="demo-fingerprint-docker-01",
            contributions=[
                {"repo": "order-service", "evidence": "Dockerfile + k8s manifests, 340 commits"}
            ],
            attribution="authored",
            existing_level="advanced",
            status="pending",
        )
    )
    db.add(
        GithubSyncRun(
            connection_id=connection.id,
            status="completed",
            repos_seen=len(repos),
            repos_detailed=len(repos),
            requests_made=9,
            started_at=days_ago(1),
            completed_at=days_ago(1),
        )
    )


async def _seed_calendar(db: AsyncSession, user: User, application_id: uuid.UUID | None) -> None:
    connection = CalendarConnection(
        user_id=user.id,
        google_email="alex.rivera.demo@personal-ai-agent.example",
        granted_scopes="https://www.googleapis.com/auth/calendar.events.readonly",
        status="connected",
        last_synced_at=days_ago(1),
    )
    db.add(connection)
    await db.flush()

    interview_at = NOW + timedelta(days=3, hours=5)
    db.add_all(
        [
            CalendarEvent(
                connection_id=connection.id,
                google_event_id="demo-event-001",
                summary="Nimbus Data Systems — Technical Screen",
                description="Video call with the backend team lead.",
                start_at=interview_at,
                end_at=interview_at + timedelta(hours=1),
                organizer_email="recruiting@nimbusdatasystems.example",
                attendees=[
                    {
                        "email": "recruiting@nimbusdatasystems.example",
                        "display_name": "Nimbus Data Systems Recruiting",
                        "response_status": "accepted",
                    }
                ],
                kind="interview",
                match_reason="Subject and organizer domain match an active application.",
                user_confirmed=True,
                application_id=application_id,
                application_match_reason="Matched to the Nimbus Data Systems application by company domain.",
            ),
            CalendarEvent(
                connection_id=connection.id,
                google_event_id="demo-event-002",
                summary="Submit BrightPath Analytics follow-up",
                start_at=NOW + timedelta(days=1),
                end_at=NOW + timedelta(days=1, hours=1),
                is_all_day=False,
                kind="deadline",
                match_reason="Self-created reminder.",
                user_confirmed=True,
            ),
            CalendarEvent(
                connection_id=connection.id,
                google_event_id="demo-event-003",
                summary="Dentist appointment",
                start_at=NOW + timedelta(days=5, hours=9),
                end_at=NOW + timedelta(days=5, hours=10),
                kind="other",
                user_confirmed=False,
            ),
        ]
    )
    db.add(
        CalendarSyncRun(
            connection_id=connection.id,
            status="completed",
            started_at=days_ago(1),
            completed_at=days_ago(1),
            events_seen=3,
            events_stored=3,
        )
    )


def _component(
    key: str,
    label: str,
    weight: int,
    status: str,
    fraction: float | None,
    summary: str,
    reason: str,
) -> dict[str, object]:
    points = round(weight * fraction) if fraction is not None else 0
    return {
        "key": key,
        "label": label,
        "weight": weight,
        "status": status,
        "fraction": fraction,
        "points": points,
        "summary": summary,
        "reason": reason,
        "details": [],
    }


async def _seed_career(db: AsyncSession, user: User, profile_stamp: str) -> uuid.UUID:
    """Returns the Nimbus Data Systems application's id, for the calendar interview event."""

    nimbus = JobPosting(
        user_id=user.id,
        source_channel="manual_paste",
        source_url=None,
        company_name="Nimbus Data Systems",
        company_domain="nimbusdatasystems.example",
        title="Senior Backend Engineer",
        location="Remote, USA",
        remote_type="remote",
        salary_min=None,
        salary_max=None,
        description_text=(
            "Senior Backend Engineer — Nimbus Data Systems (Remote, USA)\n\n"
            "Required: 5+ years of backend engineering experience.\n"
            "Required: expert-level QuantumFluxNetworking experience (our proprietary "
            "distributed systems framework).\n"
            "Required: Python and PostgreSQL experience.\n"
            "Preferred: experience with Kubernetes.\n"
            "We offer competitive pay and a fully remote culture."
        ),
        discovered_at=days_ago(12),
    )
    lumen = JobPosting(
        user_id=user.id,
        source_channel="greenhouse",
        external_id="gh-lumen-4821",
        source_url="https://boards.greenhouse.io/lumencloudworks/jobs/4821",
        company_name="Lumen Cloud Works",
        company_domain="lumencloudworks.example",
        title="Platform Engineer",
        location="Remote, USA",
        remote_type="remote",
        salary_min=150000,
        salary_max=180000,
        salary_currency="USD",
        description_text=(
            "Platform Engineer — Lumen Cloud Works\n\nRequired: 4+ years backend or platform "
            "engineering. Required: Python. Required: Kubernetes in production. Preferred: "
            "PostgreSQL. Fully remote, US-based."
        ),
        discovered_at=days_ago(16),
    )
    brightpath = JobPosting(
        user_id=user.id,
        source_channel="lever",
        external_id="lever-brightpath-9911",
        source_url="https://jobs.lever.co/brightpathanalytics/9911",
        company_name="BrightPath Analytics",
        company_domain="brightpathanalytics.example",
        title="Data Platform Engineer",
        location="Chicago, IL",
        remote_type="onsite",
        salary_min=130000,
        salary_max=155000,
        salary_currency="USD",
        description_text=(
            "Data Platform Engineer — BrightPath Analytics\n\nOnsite, 5 days/week in our "
            "Chicago office. Required: Python, SQL, data pipelines. Required: 3+ years experience."
        ),
        discovered_at=days_ago(30),
    )
    vantage = JobPosting(
        user_id=user.id,
        source_channel="manual_url",
        source_url="https://vantagerobotics.example/careers/backend-engineer",
        company_name="Vantage Robotics Global",
        company_domain=None,
        title="Backend Engineer (URGENT HIRE)",
        location="Remote — Worldwide",
        remote_type="remote",
        salary_min=220000,
        salary_max=260000,
        salary_currency="USD",
        description_text=(
            "URGENT: Backend Engineer needed immediately! Vantage Robotics Global is growing "
            "fast. No interview required for the right candidate — just send your bank details "
            "for onboarding and a laptop stipend will be wired same day. Compensation is highly "
            "competitive and negotiable."
        ),
        discovered_at=days_ago(5),
    )
    usajobs = JobPosting(
        user_id=user.id,
        source_channel="usajobs",
        external_id="usajobs-va-55210",
        source_url="https://www.usajobs.gov/job/55210",
        company_name="Dept. of Veterans Affairs",
        company_domain="va.gov",
        title="Software Developer",
        location="Remote (US)",
        remote_type="remote",
        salary_min=112000,
        salary_max=145000,
        salary_currency="USD",
        description_text=(
            "Software Developer — Department of Veterans Affairs\n\nRequired: US citizenship. "
            "Required: 3+ years Python or Java. Preferred: PostgreSQL. Remote within the US."
        ),
        discovered_at=days_ago(50),
    )
    db.add_all([nimbus, lumen, brightpath, vantage, usajobs])
    await db.flush()

    db.add(
        JobBoardFeed(
            user_id=user.id,
            board="greenhouse",
            company_slug="lumencloudworks",
            is_active=True,
            last_polled_at=days_ago(1),
        )
    )

    # Not user-owned (a global cache keyed by employer_key, shared across whoever's data
    # happens to reference the same employer) — deleting the demo user doesn't cascade to
    # these, so a re-seed must clear our own three keys first to stay idempotent.
    demo_employer_keys = [
        "nimbusdatasystems.example",
        "lumencloudworks.example",
        "name:vantage robotics global",
    ]
    await db.execute(
        delete(EmployerVerification).where(
            EmployerVerification.employer_key.in_(demo_employer_keys)
        )
    )

    db.add_all(
        [
            EmployerVerification(
                employer_key="nimbusdatasystems.example",
                company_name="Nimbus Data Systems",
                company_domain="nimbusdatasystems.example",
                verification_status="verified",
                confidence_score=82,
                rationale=(
                    "Company domain resolves to an active site with a matching official careers "
                    "page (tier: official). A secondary tech-news profile corroborates headcount "
                    "and founding year (tier: reputable_secondary). No contradicting claims found."
                ),
                checked_at=days_ago(11),
            ),
            EmployerVerification(
                employer_key="lumencloudworks.example",
                company_name="Lumen Cloud Works",
                company_domain="lumencloudworks.example",
                verification_status="verified",
                confidence_score=74,
                rationale=(
                    "Greenhouse board slug matches the company's own domain's careers redirect "
                    "(tier: official). One reputable secondary source corroborates. Salary band "
                    "wasn't independently confirmable — noted as an uncertainty, not assumed."
                ),
                checked_at=days_ago(15),
            ),
            EmployerVerification(
                employer_key="name:vantage robotics global",
                company_name="Vantage Robotics Global",
                company_domain=None,
                verification_status="suspicious",
                confidence_score=12,
                rationale=(
                    "No registrable domain was extractable from the posting. No official or "
                    "government-tier source could be found under this exact company name. The "
                    "only matches were unrelated forum mentions (tier: forum_anecdotal), which "
                    "this app never treats as corroboration on their own."
                ),
                checked_at=days_ago(5),
            ),
        ]
    )

    db.add_all(
        [
            JobFraudAssessment(
                job_posting_id=nimbus.id,
                risk_level="low",
                risk_score=6,
                signals=[],
                assessed_at=days_ago(11),
            ),
            JobFraudAssessment(
                job_posting_id=lumen.id,
                risk_level="low",
                risk_score=4,
                signals=[],
                assessed_at=days_ago(15),
            ),
            JobFraudAssessment(
                job_posting_id=brightpath.id,
                risk_level="low",
                risk_score=10,
                signals=[],
                assessed_at=days_ago(29),
            ),
            JobFraudAssessment(
                job_posting_id=vantage.id,
                risk_level="high",
                risk_score=91,
                signals=[
                    {
                        "code": "requests_banking_info",
                        "description": "Posting asks for bank details before any interview.",
                    },
                    {
                        "code": "urgency_language",
                        "description": "Posting uses high-pressure urgency language ('URGENT', 'immediately').",
                    },
                    {
                        "code": "salary_outlier",
                        "description": "Salary band is far above market for the stated role and requirements.",
                    },
                    {
                        "code": "unverifiable_employer",
                        "description": "No verifiable company domain or official presence found.",
                    },
                ],
                assessed_at=days_ago(5),
            ),
            JobFraudAssessment(
                job_posting_id=usajobs.id,
                risk_level="low",
                risk_score=2,
                signals=[],
                assessed_at=days_ago(49),
            ),
        ]
    )

    db.add_all(
        [
            JobMatch(
                job_posting_id=nimbus.id,
                status="completed",
                score_percent=85,
                assessed_weight=90,
                low_confidence=False,
                components=[
                    _component(
                        "required_skills",
                        "Required skills",
                        40,
                        "assessed",
                        0.9,
                        "Python and PostgreSQL both evidenced; QuantumFluxNetworking has no evidence.",
                        "2 of 3 required skills evidenced by profile skill versions.",
                    ),
                    _component(
                        "experience_years",
                        "Years of experience",
                        20,
                        "assessed",
                        1.0,
                        "6 years vs. 5+ required.",
                        "Profile experience spans 2018–present.",
                    ),
                    _component(
                        "preferred_skills",
                        "Preferred skills",
                        15,
                        "assessed",
                        1.0,
                        "Kubernetes evidenced.",
                        "Kubernetes skill version exists with direct evidence.",
                    ),
                    _component(
                        "remote_fit",
                        "Remote fit",
                        15,
                        "assessed",
                        1.0,
                        "Posting is remote; preference is remote.",
                        "Exact match.",
                    ),
                    _component(
                        "salary_fit",
                        "Salary fit",
                        10,
                        "not_assessed",
                        None,
                        "Posting does not publish a salary.",
                        "No salary_min/max on the posting.",
                    ),
                ],
                uncertainties=[
                    "Salary isn't published for this posting.",
                    "No direct evidence of QuantumFluxNetworking (proprietary framework) — expected for any external candidate.",
                ],
                requirements={
                    "items": [
                        {
                            "name": "5+ years backend engineering",
                            "kind": "required",
                            "quote": "Required: 5+ years of backend engineering experience.",
                        },
                        {
                            "name": "QuantumFluxNetworking",
                            "kind": "required",
                            "quote": "Required: expert-level QuantumFluxNetworking experience",
                        },
                        {
                            "name": "Python and PostgreSQL",
                            "kind": "required",
                            "quote": "Required: Python and PostgreSQL experience.",
                        },
                        {
                            "name": "Kubernetes",
                            "kind": "preferred",
                            "quote": "Preferred: experience with Kubernetes.",
                        },
                    ]
                },
                deal_breaker_check="checked",
                deal_breaker_hits=[],
                profile_stamp=profile_stamp,
                computed_at=days_ago(11),
            ),
            JobMatch(
                job_posting_id=lumen.id,
                status="completed",
                score_percent=62,
                assessed_weight=85,
                low_confidence=False,
                components=[
                    _component(
                        "required_skills",
                        "Required skills",
                        40,
                        "assessed",
                        0.5,
                        "Python evidenced; production Kubernetes evidence is thinner (one service, one migration).",
                        "1.5 of 2 required skills strongly evidenced.",
                    ),
                    _component(
                        "experience_years",
                        "Years of experience",
                        20,
                        "assessed",
                        1.0,
                        "6 years vs. 4+ required.",
                        "Profile experience exceeds requirement.",
                    ),
                    _component(
                        "preferred_skills",
                        "Preferred skills",
                        15,
                        "assessed",
                        1.0,
                        "PostgreSQL evidenced.",
                        "Direct skill-version evidence.",
                    ),
                    _component(
                        "remote_fit",
                        "Remote fit",
                        15,
                        "assessed",
                        1.0,
                        "Posting is remote; preference is remote.",
                        "Exact match.",
                    ),
                    _component(
                        "salary_fit",
                        "Salary fit",
                        10,
                        "assessed",
                        1.0,
                        "$150k–$180k is within the $140k–$190k preference band.",
                        "Overlapping ranges.",
                    ),
                ],
                uncertainties=[],
                requirements={
                    "items": [
                        {
                            "name": "4+ years backend/platform engineering",
                            "kind": "required",
                            "quote": "Required: 4+ years backend or platform engineering.",
                        },
                        {"name": "Python", "kind": "required", "quote": "Required: Python."},
                        {
                            "name": "Kubernetes in production",
                            "kind": "required",
                            "quote": "Required: Kubernetes in production.",
                        },
                        {
                            "name": "PostgreSQL",
                            "kind": "preferred",
                            "quote": "Preferred: PostgreSQL.",
                        },
                    ]
                },
                deal_breaker_check="checked",
                deal_breaker_hits=[],
                profile_stamp=profile_stamp,
                computed_at=days_ago(15),
            ),
            JobMatch(
                job_posting_id=brightpath.id,
                status="completed",
                score_percent=38,
                assessed_weight=80,
                low_confidence=True,
                components=[
                    _component(
                        "required_skills",
                        "Required skills",
                        40,
                        "assessed",
                        0.8,
                        "Python and SQL both evidenced.",
                        "Direct skill-version evidence for both.",
                    ),
                    _component(
                        "experience_years",
                        "Years of experience",
                        20,
                        "assessed",
                        1.0,
                        "6 years vs. 3+ required.",
                        "Exceeds requirement.",
                    ),
                    _component(
                        "remote_fit",
                        "Remote fit",
                        20,
                        "assessed",
                        0.0,
                        "Posting is onsite 5 days/week; preference excludes fully on-site roles.",
                        "Deal-breaker text explicitly excludes this.",
                    ),
                    _component(
                        "salary_fit",
                        "Salary fit",
                        10,
                        "assessed",
                        0.5,
                        "$130k–$155k partially overlaps the $140k–$190k preference band.",
                        "Below preferred minimum for most of the range.",
                    ),
                    _component(
                        "preferred_skills",
                        "Preferred skills",
                        10,
                        "not_assessed",
                        None,
                        "Posting lists no preferred skills.",
                        "Nothing to assess.",
                    ),
                ],
                uncertainties=[],
                requirements={
                    "items": [
                        {
                            "name": "Python, SQL, data pipelines",
                            "kind": "required",
                            "quote": "Required: Python, SQL, data pipelines.",
                        },
                        {
                            "name": "3+ years experience",
                            "kind": "required",
                            "quote": "Required: 3+ years experience.",
                        },
                    ]
                },
                deal_breaker_check="checked",
                deal_breaker_hits=[
                    {
                        "deal_breaker": "No fully on-site roles.",
                        "quote": "Onsite, 5 days/week in our Chicago office.",
                    }
                ],
                profile_stamp=profile_stamp,
                computed_at=days_ago(29),
            ),
            JobMatch(
                job_posting_id=usajobs.id,
                status="completed",
                score_percent=58,
                assessed_weight=70,
                low_confidence=True,
                components=[
                    _component(
                        "required_skills",
                        "Required skills",
                        40,
                        "assessed",
                        0.7,
                        "Python evidenced; Java has no evidence (posting accepts either).",
                        "Python strongly evidenced; Java untested by design.",
                    ),
                    _component(
                        "experience_years",
                        "Years of experience",
                        20,
                        "assessed",
                        1.0,
                        "6 years vs. 3+ required.",
                        "Exceeds requirement.",
                    ),
                    _component(
                        "remote_fit",
                        "Remote fit",
                        20,
                        "assessed",
                        1.0,
                        "Remote within the US; preference is remote.",
                        "Match.",
                    ),
                    _component(
                        "preferred_skills",
                        "Preferred skills",
                        10,
                        "assessed",
                        1.0,
                        "PostgreSQL evidenced.",
                        "Direct evidence.",
                    ),
                    _component(
                        "eligibility",
                        "US citizenship requirement",
                        10,
                        "not_assessed",
                        None,
                        "Profile has no citizenship field to check this against.",
                        "Outside what the profile records — left unassessed rather than assumed.",
                    ),
                ],
                uncertainties=[
                    "Citizenship/eligibility requirement couldn't be checked against the profile."
                ],
                requirements={
                    "items": [
                        {
                            "name": "US citizenship",
                            "kind": "required",
                            "quote": "Required: US citizenship.",
                        },
                        {
                            "name": "3+ years Python or Java",
                            "kind": "required",
                            "quote": "Required: 3+ years Python or Java.",
                        },
                        {
                            "name": "PostgreSQL",
                            "kind": "preferred",
                            "quote": "Preferred: PostgreSQL.",
                        },
                    ]
                },
                deal_breaker_check="checked",
                deal_breaker_hits=[],
                profile_stamp=profile_stamp,
                computed_at=days_ago(49),
            ),
        ]
    )

    nimbus_app = Application(
        user_id=user.id,
        job_posting_id=nimbus.id,
        status="interviewing",
        notes="Recruiter was responsive. Technical screen scheduled with the backend team lead.",
        applied_on=(days_ago(9)).date(),
        next_action_text="Prep for technical screen",
        next_action_on=(NOW + timedelta(days=3)).date(),
    )
    lumen_app = Application(
        user_id=user.id,
        job_posting_id=lumen.id,
        status="applied",
        applied_on=(days_ago(14)).date(),
        next_action_text="Follow up if no response by end of week",
        next_action_on=(NOW + timedelta(days=2)).date(),
    )
    usajobs_app = Application(
        user_id=user.id,
        job_posting_id=usajobs.id,
        status="no_response",
        applied_on=(days_ago(48)).date(),
    )
    db.add_all([nimbus_app, lumen_app, usajobs_app])
    await db.flush()

    db.add_all(
        [
            ApplicationEvent(
                application_id=nimbus_app.id,
                event_type="status_change",
                from_status=None,
                to_status="saved",
                occurred_on=(days_ago(12)).date(),
            ),
            ApplicationEvent(
                application_id=nimbus_app.id,
                event_type="status_change",
                from_status="saved",
                to_status="applied",
                occurred_on=(days_ago(9)).date(),
                snapshot={"match_score": 85},
            ),
            ApplicationEvent(
                application_id=nimbus_app.id,
                event_type="status_change",
                from_status="applied",
                to_status="interviewing",
                occurred_on=(days_ago(3)).date(),
            ),
            ApplicationEvent(
                application_id=nimbus_app.id,
                event_type="interview",
                occurred_on=(NOW + timedelta(days=3)).date(),
                body="Technical screen with the backend team lead.",
            ),
            ApplicationEvent(
                application_id=lumen_app.id,
                event_type="status_change",
                from_status=None,
                to_status="saved",
                occurred_on=(days_ago(16)).date(),
            ),
            ApplicationEvent(
                application_id=lumen_app.id,
                event_type="status_change",
                from_status="saved",
                to_status="applied",
                occurred_on=(days_ago(14)).date(),
                snapshot={"match_score": 62},
            ),
            ApplicationEvent(
                application_id=usajobs_app.id,
                event_type="status_change",
                from_status=None,
                to_status="saved",
                occurred_on=(days_ago(50)).date(),
            ),
            ApplicationEvent(
                application_id=usajobs_app.id,
                event_type="status_change",
                from_status="saved",
                to_status="applied",
                occurred_on=(days_ago(48)).date(),
                snapshot={"match_score": 58},
            ),
            ApplicationEvent(
                application_id=usajobs_app.id,
                event_type="status_change",
                from_status="applied",
                to_status="no_response",
                occurred_on=(days_ago(15)).date(),
            ),
        ]
    )

    base = await load_base_resume(db, user.id)
    resume = TailoredResume(
        user_id=user.id,
        job_posting_id=nimbus.id,
        status="completed",
        base=base.to_json(),
        requirements=[
            {
                "name": "5+ years backend engineering",
                "kind": "required",
                "quote": "Required: 5+ years of backend engineering experience.",
            },
            {
                "name": "Python and PostgreSQL",
                "kind": "required",
                "quote": "Required: Python and PostgreSQL experience.",
            },
            {
                "name": "Kubernetes",
                "kind": "preferred",
                "quote": "Preferred: experience with Kubernetes.",
            },
        ],
        gaps=[
            {
                "skill": "QuantumFluxNetworking",
                "kind": "required",
                "reason": "No evidence in the profile — proprietary to Nimbus, expected for any external candidate.",
            }
        ],
        dropped=[
            {
                "source": "llm_draft",
                "reason": 'Proposed rewrite claimed "5 years leading a QuantumFluxNetworking team" — no supporting evidence in the profile; rejected by the fact-check gate.',
            }
        ],
        profile_stamp=base.stamp(),
        started_at=days_ago(9),
    )
    db.add(resume)
    await db.flush()
    db.add_all(
        [
            ResumeChange(
                resume_id=resume.id,
                change_type="rewrite",
                target_id="summary",
                target_label="Summary",
                before_text=base.summary or "",
                after_text=(
                    "Backend engineer with 6 years building Python services on PostgreSQL, "
                    "including leading a Kubernetes migration for a high-traffic payments service."
                ),
                rationale="Foregrounds the Kubernetes migration since the posting lists it as preferred.",
                addresses=[
                    {
                        "requirement": "Kubernetes",
                        "quote": "Preferred: experience with Kubernetes.",
                    }
                ],
                decision="accepted",
                decided_at=days_ago(9),
                position=0,
            ),
            ResumeChange(
                resume_id=resume.id,
                change_type="skills_order",
                target_id="skills",
                target_label="Skills",
                before_text="\n".join(s.name for s in base.skills),
                after_text="Python\nPostgreSQL\nKubernetes\nDocker\nSystem Design",
                rationale="Moves Python and PostgreSQL (both required) ahead of Kubernetes (preferred).",
                addresses=[
                    {
                        "requirement": "Python and PostgreSQL",
                        "quote": "Required: Python and PostgreSQL experience.",
                    }
                ],
                decision="accepted",
                decided_at=days_ago(9),
                position=1,
            ),
        ]
    )

    letter = CoverLetter(
        user_id=user.id,
        job_posting_id=nimbus.id,
        status="completed",
        base=base.to_json(),
        requirements=[
            {
                "name": "Python and PostgreSQL",
                "kind": "required",
                "quote": "Required: Python and PostgreSQL experience.",
            }
        ],
        gaps=[
            {
                "skill": "QuantumFluxNetworking",
                "kind": "required",
                "reason": "No evidence in the profile.",
            }
        ],
        dropped=[
            {
                "sentence": "I've been following Nimbus's proprietary QuantumFluxNetworking research for years.",
                "reason": "No evidence this is true — rejected by fact-checking.",
            }
        ],
        profile_stamp=base.stamp(),
        started_at=days_ago(9),
    )
    db.add(letter)
    await db.flush()
    db.add_all(
        [
            CoverLetterParagraph(
                letter_id=letter.id,
                position=0,
                role="opening",
                text="I'm writing to apply for the Senior Backend Engineer role at Nimbus Data Systems.",
                sentences=[
                    {
                        "text": "I'm writing to apply for the Senior Backend Engineer role at Nimbus Data Systems.",
                        "kind": "framing",
                        "supports": [],
                    }
                ],
                decision="accepted",
                decided_at=days_ago(9),
            ),
            CoverLetterParagraph(
                letter_id=letter.id,
                position=1,
                role="body",
                text=(
                    "Over six years at Acme Corp and Bluewave Software, I've built and maintained "
                    "Python services on PostgreSQL handling millions of daily requests, and led the "
                    "migration of a monolith onto Kubernetes."
                ),
                sentences=[
                    {
                        "text": "Over six years at Acme Corp and Bluewave Software, I've built and maintained Python services on PostgreSQL handling millions of daily requests, and led the migration of a monolith onto Kubernetes.",
                        "kind": "fact",
                        "supports": [
                            {
                                "type": "profile_experience",
                                "ref": "exp",
                                "label": "Acme Corp",
                                "excerpt": "Led migration of a monolith to a service-oriented architecture.",
                            }
                        ],
                    }
                ],
                decision="accepted",
                decided_at=days_ago(9),
            ),
            CoverLetterParagraph(
                letter_id=letter.id,
                position=2,
                role="closing",
                text="I'd welcome the chance to talk about how that experience applies to your backend team.",
                sentences=[
                    {
                        "text": "I'd welcome the chance to talk about how that experience applies to your backend team.",
                        "kind": "framing",
                        "supports": [],
                    }
                ],
                decision="accepted",
                decided_at=days_ago(9),
            ),
        ]
    )

    session = PracticeSession(
        user_id=user.id,
        job_posting_id=nimbus.id,
        application_id=nimbus_app.id,
        status="completed",
        requirements=[
            {
                "name": "Python and PostgreSQL",
                "kind": "required",
                "quote": "Required: Python and PostgreSQL experience.",
            }
        ],
        profile_stamp=base.stamp(),
        started_at=days_ago(4),
    )
    db.add(session)
    await db.flush()
    db.add_all(
        [
            PracticeQuestion(
                session_id=session.id,
                position=0,
                text="Tell me about a time you led a significant infrastructure migration.",
                category="behavioral",
                ref_type="profile_experience",
                ref_name="Acme Corp — Senior Backend Engineer",
                ref_excerpt="Led migration of a monolith to a service-oriented architecture. Introduced Kubernetes for the payments service's rollout in 2024.",
                answer_text=(
                    "I led the move of our payments service from a monolith onto Kubernetes in 2024. "
                    "The main risk was zero-downtime rollout, so we ran both stacks in parallel behind "
                    "a feature flag for two weeks before fully cutting over."
                ),
                answered_at=days_ago(4),
                verdict="addressed",
                feedback_text="Strong answer — grounded in the specific migration from your profile, with a concrete risk-mitigation detail.",
            ),
            PracticeQuestion(
                session_id=session.id,
                position=1,
                text="How would you design a rate limiter for a public API?",
                category="technical",
                ref_type="posting_requirement",
                ref_name="Python and PostgreSQL",
                ref_excerpt="Required: Python and PostgreSQL experience.",
                answer_text="I'd use a token-bucket approach backed by Redis for shared state across instances.",
                answered_at=days_ago(4),
                verdict="partially_addressed",
                feedback_text="Good high-level design, but didn't address per-user vs. per-IP limiting or what happens when Redis is unavailable.",
            ),
            PracticeQuestion(
                session_id=session.id,
                position=2,
                text="Describe a disagreement you had with a teammate about a technical approach.",
                category="behavioral",
                ref_type="profile_skill",
                ref_name="System Design",
                ref_excerpt="Led the monolith-to-services migration end to end.",
                answer_text=None,
                verdict="missed",
                feedback_text="Not answered — this is a common interview question worth preparing for before the real screen.",
            ),
        ]
    )

    return nimbus_app.id


async def _seed_research(db: AsyncSession, user: User) -> None:
    url = "https://www.crunchbase.com/organization/nimbus-data-systems"
    normalized = normalize_url(url)
    source = (
        await db.execute(select(ResearchSource).where(ResearchSource.normalized_url == normalized))
    ).scalar_one_or_none()
    if source is None:
        source = ResearchSource(
            normalized_url=normalized,
            original_url=url,
            domain="crunchbase.com",
            title="Nimbus Data Systems — Company Profile",
            tier="reputable_secondary",
            tier_rationale="Crunchbase is a reputable secondary source for company/funding facts, not an official primary source.",
            content="Nimbus Data Systems is a distributed-systems infrastructure company founded in 2019, based in Austin, TX.",
            http_status=200,
            fetched_at=days_ago(11),
        )
        db.add(source)
        await db.flush()

    query = ResearchQuery(
        user_id=user.id,
        query_text="Is Nimbus Data Systems a real, legitimate employer?",
        purpose="employer_verification",
        status="completed",
        created_at=days_ago(11),
        completed_at=days_ago(11),
    )
    db.add(query)
    await db.flush()

    db.add(
        ResearchQuerySource(
            query_id=query.id,
            source_id=source.id,
            search_rank=1,
            search_snippet="Nimbus Data Systems — Company Profile",
        )
    )

    claim = ResearchClaim(
        query_id=query.id,
        claim_text="Nimbus Data Systems is an active, registered company founded in 2019.",
        claim_type="company_fact",
        status="single_source",
        confidence_score=70,
        confidence_rationale="Corroborated by one reputable secondary source; no official-tier source was independently found in this pass.",
    )
    db.add(claim)
    await db.flush()
    db.add(
        ResearchClaimCitation(
            claim_id=claim.id,
            source_id=source.id,
            excerpt="Nimbus Data Systems is a distributed-systems infrastructure company founded in 2019, based in Austin, TX.",
            stance="supports",
            excerpt_verified=True,
        )
    )
    db.add(
        ResearchReport(
            query_id=query.id,
            summary=(
                "Nimbus Data Systems appears to be a real, active company founded in 2019 and based "
                "in Austin, TX, per a reputable secondary source. No official government registry "
                "lookup was performed in this pass."
            ),
            uncertainties=[
                "No official/government-tier source was checked in this pass — this rests on one reputable secondary source."
            ],
            claim_ids=[str(claim.id)],
            model_used="demo-seed (no live LLM call)",
            generated_at=days_ago(11),
        )
    )


async def _seed_audit(db: AsyncSession, user: User) -> None:
    db.add_all(
        [
            AuditLog(
                user_id=user.id,
                action="career.resume.exported",
                risk_level="green",
                status="completed",
                summary="Exported a tailored resume as Markdown.",
                evidence={"accepted": 2},
                resource_type="tailored_resume",
                requested_at=days_ago(9),
            ),
            AuditLog(
                user_id=user.id,
                action="career.cover_letter.exported",
                risk_level="green",
                status="completed",
                summary="Exported a cover letter as text.",
                evidence={"accepted": 3, "edited_not_fact_checked": 0},
                resource_type="cover_letter",
                requested_at=days_ago(9),
            ),
            AuditLog(
                user_id=user.id,
                action="account.delete_all_data.requested",
                risk_level="red",
                status="rejected",
                summary="Requested full account data deletion.",
                evidence={"reason": "exploring the settings page"},
                second_check_passed=None,
                decided_at=days_ago(20),
                decided_by=user.id,
                requested_at=days_ago(20),
            ),
        ]
    )


async def seed() -> None:
    async with async_session_factory() as db:
        await _delete_existing_demo_user(db)
        user = await _seed_user(db)
        await _seed_profile(db, user)
        await _seed_gmail(db, user)
        await _seed_github(db, user)
        await db.flush()

        base = await load_base_resume(db, user.id)
        nimbus_application_id = await _seed_career(db, user, base.stamp())
        await _seed_calendar(db, user, nimbus_application_id)
        await _seed_research(db, user)
        await _seed_audit(db, user)
        await db.commit()

        await create_digest(db, user.id, trigger="demo_seed")
        await db.commit()

    print(f"Seeded demo user {DEMO_USER_EMAIL}")


if __name__ == "__main__":
    asyncio.run(seed())
