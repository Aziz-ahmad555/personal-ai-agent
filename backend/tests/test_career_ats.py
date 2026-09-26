"""ATS checks through the API: it needs a completed match, checks the resume as it stands for the
job (tailored draft if the user accepted changes, else the profile-built one), and offers an
ATS-safe plain-text export."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.models import AuditLog
from app.auth.security import hash_password
from app.career import resume_service
from app.career.models import JobMatch, JobPosting
from app.db.models import User

OWNER = "profile-owner@example.com"

DESCRIPTION = (
    "ML Engineer at Acme Corp. Requirements: strong Python skills and Kubernetes experience. "
    "Nice to have: Docker."
)
MATCH_REQUIREMENTS = {
    "required_skills": [
        {"name": "Python", "quote": "strong Python skills"},
        {"name": "Kubernetes", "quote": "Kubernetes experience"},
    ],
    "preferred_skills": [{"name": "Docker", "quote": "Nice to have: Docker"}],
}
EXP_A_TEXT = "Built a fraud detection web application using Flask, SQLAlchemy and XGBoost."
EXP_B_TEXT = "Building a real-time multimodal AI platform for emergency detection."


class _FakeLLM:
    def __init__(self, proposals: list[dict]) -> None:
        self._proposals = proposals

    async def generate_structured(self, **kwargs: object) -> dict:
        assert kwargs["schema_name"] == "propose_resume_rewrites"
        return {"changes": self._proposals}


async def _setup_profile(
    client: AsyncClient,
    headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> dict[str, str]:
    await client.put(
        "/profile",
        headers=headers,
        json={
            "headline": "ML/AI Engineer",
            "summary": "Engineer who builds machine learning systems and APIs.",
            "location": "Lahore",
        },
    )
    async with session_factory() as db:
        user = (await db.execute(select(User).where(User.email == OWNER))).scalar_one()
        user.full_name = "Aziz Ahmad"
        await db.commit()
    ids: dict[str, str] = {}
    for key, company, title, start, description in (
        ("a", "University", "Vaultic", "2026-03-01", EXP_A_TEXT),
        ("b", "Individual", "AegisAI", "2026-07-01", EXP_B_TEXT),
    ):
        created = await client.post(
            "/profile/experience",
            headers=headers,
            json={
                "company": company,
                "title": title,
                "start_date": start,
                "description": description,
            },
        )
        ids[key] = created.json()["id"]
    for name, linked in (("FastAPI", None), ("Python", ids["a"])):
        skill = await client.post("/profile/skills", headers=headers, json={"name": name})
        await client.post(
            f"/profile/skills/{skill.json()['id']}/versions",
            headers=headers,
            json={
                "level": "advanced",
                "evidence": f"Built and shipped systems using {name}.",
                "work_experience_id": linked,
            },
        )
    await client.post("/profile/skills", headers=headers, json={"name": "Docker"})  # no evidence
    return ids


async def _make_job(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    email: str = OWNER,
    with_match: bool = True,
) -> str:
    async with session_factory() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one()
        job = JobPosting(
            user_id=user.id,
            source_channel="manual_paste",
            title="ML Engineer",
            company_name="Acme Corp",
            remote_type="remote",
            description_text=DESCRIPTION,
        )
        db.add(job)
        await db.flush()
        if with_match:
            db.add(
                JobMatch(
                    job_posting_id=job.id,
                    status="completed",
                    score_percent=50,
                    assessed_weight=50,
                    low_confidence=False,
                    requirements=MATCH_REQUIREMENTS,
                )
            )
        await db.commit()
        return str(job.id)


async def _check(client: AsyncClient, headers: dict[str, str], job_id: str):
    return await client.post(f"/career/jobs/{job_id}/ats-check", headers=headers)


async def test_a_completed_match_is_required_and_the_message_says_what_to_do(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    job_id = await _make_job(session_factory, with_match=False)

    response = await _check(client, auth_headers, job_id)

    assert response.status_code == 409
    assert "Run the match for this job first" in response.json()["detail"]


async def test_the_check_reports_keyword_states_and_structure_for_the_profile_resume(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _setup_profile(client, auth_headers, session_factory)
    job_id = await _make_job(session_factory)

    response = await _check(client, auth_headers, job_id)

    assert response.status_code == 200
    body = response.json()
    assert (body["resume_source"], body["accepted_changes"]) == ("profile", 0)

    keywords = {k["name"]: k for k in body["keywords"]}
    # Python is in the Skills list only; its evidence points at the Vaultic role.
    assert keywords["Python"]["state"] == "listed_only"
    assert keywords["Python"]["roles"] == ["Vaultic — University"]
    assert keywords["Kubernetes"]["state"] == "gap"
    kubernetes = keywords["Kubernetes"]
    assert kubernetes["detail"] == "It isn't in your profile, so it isn't on your resume."
    assert keywords["Docker"]["state"] == "gap"
    assert "no evidence recorded" in keywords["Docker"]["detail"]
    assert body["keyword_stats"] == {
        "required_found": 1,
        "required_total": 2,
        "preferred_found": 0,
        "preferred_total": 1,
        "in_context": 0,
        "coverage_percent": 33,
    }

    checks = {c["key"]: c for c in body["checks"]}
    assert checks["contact"]["status"] == "fail"  # the profile stores no contact details
    assert checks["hazards"]["status"] == "warn"  # the Markdown export's dashes and '#'
    assert checks["sections"]["status"] == "warn"  # this profile has no education entry
    assert "no Education section" in checks["sections"]["detail"]
    assert checks["order"]["status"] == "pass"
    assert body["summary"]["fail"] == 1
    assert len(body["limitations"]) == 3
    assert "can't tell you how a specific employer's system" in body["limitations"][0]


async def test_a_tailored_resume_with_accepted_changes_is_what_gets_checked(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = await _setup_profile(client, auth_headers, session_factory)
    job_id = await _make_job(session_factory)
    monkeypatch.setattr(
        resume_service,
        "get_llm_provider",
        lambda settings: _FakeLLM(
            [
                {
                    "source_id": f"exp:{ids['a']}",
                    "new_text": "Developed a fraud detection web application in Python with "
                    "Flask, SQLAlchemy and XGBoost.",
                    "addresses": ["Python"],
                    "rationale": "Shows Python in use.",
                }
            ]
        ),
    )
    await client.post(f"/career/jobs/{job_id}/tailor", headers=auth_headers)
    draft = (await client.get(f"/career/jobs/{job_id}/resume", headers=auth_headers)).json()
    rewrite = next(c for c in draft["changes"] if c["change_type"] == "rewrite")

    before = (await _check(client, auth_headers, job_id)).json()
    assert before["resume_source"] == "profile"  # nothing accepted yet

    await client.post(
        f"/career/resumes/{draft['id']}/changes/{rewrite['id']}/decision",
        headers=auth_headers,
        json={"decision": "accepted"},
    )
    after = (await _check(client, auth_headers, job_id)).json()

    assert (after["resume_source"], after["accepted_changes"]) == ("tailored", 1)
    keywords = {k["name"]: k["state"] for k in after["keywords"]}
    assert keywords["Python"] == "in_context"  # now used in a role, not just listed


async def test_the_check_is_deterministic_and_audited(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _setup_profile(client, auth_headers, session_factory)
    job_id = await _make_job(session_factory)

    first = (await _check(client, auth_headers, job_id)).json()
    second = (await _check(client, auth_headers, job_id)).json()

    assert first == second
    async with session_factory() as db:
        entry = (
            (await db.execute(select(AuditLog).where(AuditLog.action == "career.ats.checked")))
            .scalars()
            .first()
        )
    assert entry is not None
    assert entry.evidence["keyword_coverage_percent"] == 33
    assert entry.evidence["resume_source"] == "profile"


async def test_the_ats_safe_export_is_plain_ascii_with_standard_headings_and_needs_no_match(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _setup_profile(client, auth_headers, session_factory)
    job_id = await _make_job(session_factory, with_match=False)

    response = await client.get(f"/career/jobs/{job_id}/ats-safe", headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["filename"] == "resume-acme-corp-ml-engineer-ats-safe.txt"
    assert (body["resume_source"], body["accepted_changes"]) == ("profile", 0)
    text = body["text"]
    assert text.startswith("Aziz Ahmad\nML/AI Engineer\nLahore\n")
    assert "EDUCATION" not in text  # this profile has no education entry, so no empty section
    for heading in ("SUMMARY", "EXPERIENCE", "SKILLS"):
        assert f"\n{heading}\n" in text
    assert "Vaultic - University" in text
    assert text.isascii()
    assert "#" not in text
    async with session_factory() as db:
        actions = set((await db.execute(select(AuditLog.action))).scalars().all())
    assert "career.ats.safe_exported" in actions


async def test_other_users_jobs_are_invisible(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as db:
        db.add(User(email="other@example.com", hashed_password=hash_password("x-y-z-123456")))
        await db.commit()
    foreign = await _make_job(session_factory, email="other@example.com")

    assert (await _check(client, auth_headers, foreign)).status_code == 404
    safe = await client.get(f"/career/jobs/{foreign}/ats-safe", headers=auth_headers)
    assert safe.status_code == 404
