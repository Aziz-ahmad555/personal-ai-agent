"""Resume tailoring through the API, with an LLM that misbehaves on purpose: it tries to slip in
skills, numbers, and names the profile doesn't support, and every such attempt must be dropped
(and reported), while honest edits reach the user as suggestions they accept or reject."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.models import AuditLog
from app.auth.security import hash_password
from app.career import resume_service
from app.career.models import JobMatch, JobPosting, TailoredResume
from app.db.models import User
from app.research.llm import LLMError

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
SUMMARY = "Engineer who builds machine learning systems and APIs."


class _FakeLLM:
    def __init__(
        self,
        proposals: list[dict] | None = None,
        *,
        fail: bool = False,
        requirements: dict | None = None,
    ) -> None:
        self._proposals = proposals or []
        self._fail = fail
        self._requirements = requirements
        self.requirement_calls = 0

    async def generate_structured(self, **kwargs: object) -> dict:
        if self._fail:
            raise LLMError("Gemini call failed: 503 UNAVAILABLE")
        if kwargs["schema_name"] == "record_job_requirements":
            self.requirement_calls += 1
            assert self._requirements is not None, "requirements were re-extracted unexpectedly"
            return self._requirements
        return {"changes": self._proposals}


def _use_llm(monkeypatch: pytest.MonkeyPatch, llm: _FakeLLM) -> None:
    monkeypatch.setattr(resume_service, "get_llm_provider", lambda settings: llm)


async def _setup_profile(client: AsyncClient, headers: dict[str, str]) -> dict[str, str]:
    """A profile with two roles and evidence-backed skills; returns the two role ids."""
    await client.put(
        "/profile",
        headers=headers,
        json={"headline": "ML/AI Engineer", "summary": SUMMARY, "location": "Lahore"},
    )
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
        assert created.status_code == 201, created.text
        ids[key] = created.json()["id"]

    # FastAPI first, Python second, so the posting's Python has to move up.
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
    # Asserted with no evidence: must be reported as a gap, never written into the resume.
    await client.post("/profile/skills", headers=headers, json={"name": "Docker"})
    return ids


async def _make_job(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    email: str = OWNER,
    description: str | None = DESCRIPTION,
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
            description_text=description,
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


async def _code(client: AsyncClient, method: str, path: str, headers: dict[str, str]) -> int:
    return (await getattr(client, method)(path, headers=headers)).status_code


async def _tailor(client: AsyncClient, headers: dict[str, str], job_id: str) -> dict:
    started = await client.post(f"/career/jobs/{job_id}/tailor", headers=headers)
    assert started.status_code == 202
    fetched = await client.get(f"/career/jobs/{job_id}/resume", headers=headers)
    assert fetched.status_code == 200, fetched.text
    return fetched.json()


def _misbehaving_proposals(exp_a: str, exp_b: str) -> list[dict]:
    return [
        # Honest: rephrases exactly what the role already says.
        {
            "source_id": f"exp:{exp_a}",
            "new_text": "Developed a fraud detection web application with Flask, SQLAlchemy "
            "and XGBoost.",
            "addresses": ["Python"],
            "rationale": "Leads with the application-building the posting cares about.",
        },
        # Fabricates a skill the posting wants and the profile lacks.
        {
            "source_id": f"exp:{exp_b}",
            "new_text": "Building a real-time multimodal AI platform on Kubernetes.",
            "addresses": ["Kubernetes"],
            "rationale": "Speaks to the Kubernetes requirement.",
        },
        # Fabricates a number.
        {
            "source_id": "summary",
            "new_text": "Engineer with 5 years building machine learning systems and APIs.",
            "addresses": ["Python"],
            "rationale": "Adds seniority.",
        },
        # Points at something that isn't on the resume.
        {
            "source_id": "exp:does-not-exist",
            "new_text": "Led a team.",
            "addresses": ["Python"],
            "rationale": "n/a",
        },
    ]


async def test_honest_edits_surface_and_fabricated_ones_are_dropped_and_reported(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = await _setup_profile(client, auth_headers)
    llm = _FakeLLM(_misbehaving_proposals(ids["a"], ids["b"]))
    _use_llm(monkeypatch, llm)
    job_id = await _make_job(session_factory)

    resume = await _tailor(client, auth_headers, job_id)

    assert resume["status"] == "completed"
    assert llm.requirement_calls == 0  # reused the match's already-verified requirements
    assert [c["change_type"] for c in resume["changes"]] == ["rewrite", "skills_order"]
    assert all(c["decision"] == "pending" for c in resume["changes"])
    rewrite = resume["changes"][0]
    assert rewrite["target_label"] == "Vaultic — University"
    assert rewrite["before_text"] == EXP_A_TEXT
    assert rewrite["addresses"] == [{"requirement": "Python", "quote": "strong Python skills"}]

    reasons = {d["source"]: d["reason"] for d in resume["dropped"]}
    assert "claims 'Kubernetes'" in reasons["AegisAI — Individual"]
    assert "adds number(s)" in reasons["Professional summary"]
    assert "isn't on your resume" in reasons["exp:does-not-exist"]

    gaps = {g["skill"]: g for g in resume["gaps"]}
    assert gaps["Kubernetes"] == {
        "skill": "Kubernetes",
        "kind": "required",
        "reason": "it isn't in your profile",
    }
    assert gaps["Docker"]["reason"] == "it's in your profile, but with no evidence recorded"
    assert "Python" not in gaps  # covered by evidence

    # Nothing has been accepted, so the resume is still exactly the original.
    assert EXP_A_TEXT in resume["preview_markdown"]
    assert "Developed a fraud detection" not in resume["preview_markdown"]
    assert "Kubernetes" not in resume["preview_markdown"]
    assert "Docker" not in resume["preview_markdown"]  # unevidenced skill never appears


async def test_accepting_and_rejecting_changes_controls_the_output(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = await _setup_profile(client, auth_headers)
    _use_llm(monkeypatch, _FakeLLM(_misbehaving_proposals(ids["a"], ids["b"])))
    job_id = await _make_job(session_factory)
    resume = await _tailor(client, auth_headers, job_id)
    rewrite, skills = resume["changes"]
    assert skills["before_text"] == "FastAPI\nPython"
    assert skills["after_text"] == "Python\nFastAPI"

    accepted = await client.post(
        f"/career/resumes/{resume['id']}/changes/{rewrite['id']}/decision",
        headers=auth_headers,
        json={"decision": "accepted"},
    )
    assert accepted.status_code == 200
    body = accepted.json()
    assert body["counts"] == {"accepted": 1, "rejected": 0, "pending": 1}
    assert "Developed a fraud detection web application" in body["preview_markdown"]
    assert EXP_A_TEXT not in body["preview_markdown"]
    assert body["preview_markdown"].rstrip().endswith("FastAPI, Python")  # skills still pending

    rejected = await client.post(
        f"/career/resumes/{resume['id']}/changes/{skills['id']}/decision",
        headers=auth_headers,
        json={"decision": "rejected"},
    )
    assert rejected.json()["preview_markdown"].rstrip().endswith("FastAPI, Python")
    assert rejected.json()["counts"] == {"accepted": 1, "rejected": 1, "pending": 0}

    # Changing your mind: accept it after all.
    flipped = await client.post(
        f"/career/resumes/{resume['id']}/changes/{skills['id']}/decision",
        headers=auth_headers,
        json={"decision": "accepted"},
    )
    assert flipped.json()["preview_markdown"].rstrip().endswith("Python, FastAPI")

    async with session_factory() as db:
        actions = set((await db.execute(select(AuditLog.action))).scalars().all())
    assert {"career.resume.tailored", "career.resume.change_accepted"} <= actions
    assert "career.resume.change_rejected" in actions


async def test_requirements_are_extracted_when_the_job_has_no_match(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _setup_profile(client, auth_headers)
    llm = _FakeLLM(
        [],
        requirements={
            "required_skills": [
                {"name": "Python", "quote": "strong Python skills"},
                {"name": "Rust", "quote": "made-up quote not in the posting"},  # dropped
            ],
            "preferred_skills": [],
        },
    )
    _use_llm(monkeypatch, llm)
    job_id = await _make_job(session_factory, with_match=False)

    resume = await _tailor(client, auth_headers, job_id)

    assert resume["status"] == "completed"
    assert llm.requirement_calls == 1
    assert [g["skill"] for g in resume["gaps"]] == []  # only Python survived, and it's covered


async def test_llm_outage_is_a_clear_failure_not_a_guess(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _setup_profile(client, auth_headers)
    _use_llm(monkeypatch, _FakeLLM(fail=True))
    job_id = await _make_job(session_factory)

    resume = await _tailor(client, auth_headers, job_id)

    assert resume["status"] == "failed"
    assert "503" in resume["error"]
    assert resume["changes"] == []


async def test_nothing_to_tailor_gives_actionable_messages(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_llm(monkeypatch, _FakeLLM())

    empty_profile_job = await _make_job(session_factory)
    empty = await _tailor(client, auth_headers, empty_profile_job)
    assert empty["status"] == "failed"
    assert "no summary or work-history descriptions" in empty["error"]

    await _setup_profile(client, auth_headers)
    no_description = await _make_job(session_factory, description=None)
    resume = await _tailor(client, auth_headers, no_description)
    assert resume["status"] == "failed"
    assert "paste the full posting" in resume["error"]


async def test_a_draft_goes_stale_when_the_profile_changes(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _setup_profile(client, auth_headers)
    _use_llm(monkeypatch, _FakeLLM())
    job_id = await _make_job(session_factory)
    assert (await _tailor(client, auth_headers, job_id))["is_stale"] is False

    await client.put("/profile", headers=auth_headers, json={"summary": "A rewritten summary."})

    stale = await client.get(f"/career/jobs/{job_id}/resume", headers=auth_headers)
    assert stale.json()["is_stale"] is True
    assert (await _tailor(client, auth_headers, job_id))["is_stale"] is False


async def test_regenerating_discards_the_old_draft_and_its_decisions(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = await _setup_profile(client, auth_headers)
    _use_llm(monkeypatch, _FakeLLM(_misbehaving_proposals(ids["a"], ids["b"])))
    job_id = await _make_job(session_factory)
    first = await _tailor(client, auth_headers, job_id)
    await client.post(
        f"/career/resumes/{first['id']}/changes/{first['changes'][0]['id']}/decision",
        headers=auth_headers,
        json={"decision": "accepted"},
    )

    second = await _tailor(client, auth_headers, job_id)

    assert second["id"] == first["id"]  # one draft per job
    assert second["counts"] == {"accepted": 0, "rejected": 0, "pending": 2}
    assert {c["id"] for c in second["changes"]}.isdisjoint({c["id"] for c in first["changes"]})


async def test_an_orphaned_run_is_reported_failed_not_running_forever(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    job_id = await _make_job(session_factory)
    async with session_factory() as db:
        user = (await db.execute(select(User).where(User.email == OWNER))).scalar_one()
        db.add(
            TailoredResume(
                user_id=user.id,
                job_posting_id=uuid.UUID(job_id),
                status="running",
                started_at=datetime.now(UTC) - timedelta(minutes=20),
            )
        )
        await db.commit()

    resume = (await client.get(f"/career/jobs/{job_id}/resume", headers=auth_headers)).json()

    assert resume["status"] == "failed"
    assert "didn't finish" in resume["error"]


async def test_export_returns_markdown_with_only_accepted_changes(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = await _setup_profile(client, auth_headers)
    _use_llm(monkeypatch, _FakeLLM(_misbehaving_proposals(ids["a"], ids["b"])))
    job_id = await _make_job(session_factory)
    resume = await _tailor(client, auth_headers, job_id)
    await client.post(
        f"/career/resumes/{resume['id']}/changes/{resume['changes'][0]['id']}/decision",
        headers=auth_headers,
        json={"decision": "accepted"},
    )

    export = await client.get(f"/career/resumes/{resume['id']}/export", headers=auth_headers)

    assert export.status_code == 200
    body = export.json()
    assert body["filename"] == "resume-acme-corp-ml-engineer.md"
    assert (body["accepted"], body["pending"], body["rejected"]) == (1, 1, 0)
    assert body["markdown"].startswith("# ML/AI Engineer\nLahore\n")
    assert "Developed a fraud detection web application" in body["markdown"]
    async with session_factory() as db:
        actions = set((await db.execute(select(AuditLog.action))).scalars().all())
    assert "career.resume.exported" in actions


async def test_a_draft_that_isnt_ready_cannot_be_exported(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _setup_profile(client, auth_headers)
    _use_llm(monkeypatch, _FakeLLM(fail=True))
    job_id = await _make_job(session_factory)
    failed = await _tailor(client, auth_headers, job_id)

    response = await client.get(f"/career/resumes/{failed['id']}/export", headers=auth_headers)

    assert response.status_code == 409


async def test_decisions_are_validated(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = await _setup_profile(client, auth_headers)
    _use_llm(monkeypatch, _FakeLLM(_misbehaving_proposals(ids["a"], ids["b"])))
    job_id = await _make_job(session_factory)
    resume = await _tailor(client, auth_headers, job_id)
    base = f"/career/resumes/{resume['id']}/changes"

    bad_value = await client.post(
        f"{base}/{resume['changes'][0]['id']}/decision",
        headers=auth_headers,
        json={"decision": "maybe"},
    )
    unknown = await client.post(
        f"{base}/{uuid.uuid4()}/decision", headers=auth_headers, json={"decision": "accepted"}
    )

    assert bad_value.status_code == 422
    assert unknown.status_code == 404


async def test_other_users_jobs_and_drafts_are_invisible(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as db:
        other = User(email="other@example.com", hashed_password=hash_password("x-y-z-123456"))
        db.add(other)
        await db.commit()
        job = JobPosting(user_id=other.id, source_channel="manual_paste", title="T")
        db.add(job)
        await db.commit()
        foreign_resume = TailoredResume(user_id=other.id, job_posting_id=job.id, status="completed")
        db.add(foreign_resume)
        await db.commit()
        job_id, resume_id = str(job.id), str(foreign_resume.id)

    assert await _code(client, "post", f"/career/jobs/{job_id}/tailor", auth_headers) == 404
    assert await _code(client, "get", f"/career/jobs/{job_id}/resume", auth_headers) == 404
    assert await _code(client, "get", f"/career/resumes/{resume_id}/export", auth_headers) == 404
    assert await _code(client, "delete", f"/career/resumes/{resume_id}", auth_headers) == 404


async def test_no_draft_yet_is_a_404_and_delete_removes_one(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _setup_profile(client, auth_headers)
    _use_llm(monkeypatch, _FakeLLM())
    job_id = await _make_job(session_factory)
    assert await _code(client, "get", f"/career/jobs/{job_id}/resume", auth_headers) == 404
    resume = await _tailor(client, auth_headers, job_id)

    gone = await client.delete(f"/career/resumes/{resume['id']}", headers=auth_headers)

    assert gone.status_code == 204
    assert await _code(client, "get", f"/career/jobs/{job_id}/resume", auth_headers) == 404
    assert (await client.get(f"/career/jobs/{job_id}", headers=auth_headers)).status_code == 200


async def test_a_change_that_addresses_no_posting_requirement_is_dropped(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _setup_profile(client, auth_headers)
    _use_llm(
        monkeypatch,
        _FakeLLM(
            [
                {
                    "source_id": "summary",
                    "new_text": "Engineer building machine learning systems and APIs.",
                    "addresses": ["Team spirit"],
                    "rationale": "Sounds nicer.",
                }
            ]
        ),
    )
    job_id = await _make_job(session_factory)

    resume = await _tailor(client, auth_headers, job_id)

    assert [c["change_type"] for c in resume["changes"]] == ["skills_order"]  # no rewrite
    assert resume["dropped"] == [
        {
            "source": "Professional summary",
            "reason": "it didn't address any requirement from the posting",
        }
    ]


async def test_only_the_first_proposal_per_item_is_considered(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _setup_profile(client, auth_headers)
    honest = {
        "source_id": "summary",
        "new_text": "Engineer building machine learning systems and APIs in Python.",
        "addresses": ["Python"],
        "rationale": "Names the language the posting wants.",
    }
    fabricated = {**honest, "new_text": "Engineer with 10 years of machine learning experience."}
    _use_llm(monkeypatch, _FakeLLM([honest, fabricated]))
    job_id = await _make_job(session_factory)

    resume = await _tailor(client, auth_headers, job_id)

    rewrites = [c for c in resume["changes"] if c["change_type"] == "rewrite"]
    assert [c["after_text"] for c in rewrites] == [honest["new_text"]]
    assert resume["dropped"] == []
