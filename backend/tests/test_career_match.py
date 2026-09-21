"""End-to-end match tests through the API. The LLM and embeddings are faked, so this checks
the orchestration: verified requirements -> profile facts -> score -> stored breakdown, plus
staleness detection, failure states, and the deal-breaker check."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.security import hash_password
from app.career import match_service
from app.career.models import JobMatch, JobPosting
from app.db.models import User
from app.research.llm import LLMError

DESCRIPTION = (
    "Senior ML Engineer, fully remote. Requirements: 3+ years of experience, strong Python "
    "and TensorFlow skills. Nice to have: Kubernetes. Salary range $150,000-$190,000. "
    "On-call weekends are required."
)

REQUIREMENTS_PAYLOAD = {
    "required_skills": [
        {"name": "Python", "quote": "strong Python and TensorFlow skills"},
        {"name": "TensorFlow", "quote": "strong Python and TensorFlow skills"},
    ],
    "preferred_skills": [{"name": "Kubernetes", "quote": "Nice to have: Kubernetes"}],
    "min_years_experience": {"years": 3, "quote": "3+ years of experience"},
}


class _FakeLLM:
    """Dispatches on the schema being requested, since one match makes up to two calls."""

    def __init__(
        self,
        *,
        requirements: dict | None = None,
        hits: list[dict] | None = None,
        fail_requirements: bool = False,
        fail_deal_breakers: bool = False,
    ) -> None:
        self._requirements = requirements if requirements is not None else REQUIREMENTS_PAYLOAD
        self._hits = hits or []
        self._fail_requirements = fail_requirements
        self._fail_deal_breakers = fail_deal_breakers

    async def generate_structured(self, **kwargs: object) -> dict:
        if kwargs["schema_name"] == "record_job_requirements":
            if self._fail_requirements:
                raise LLMError("Gemini call failed: 503 UNAVAILABLE")
            return self._requirements
        if self._fail_deal_breakers:
            raise LLMError("Gemini call failed: 503 UNAVAILABLE")
        return {"hits": self._hits}


def _use_llm(monkeypatch: pytest.MonkeyPatch, llm: _FakeLLM) -> None:
    monkeypatch.setattr(match_service, "get_llm_provider", lambda settings: llm)


async def _make_job(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    email: str = "profile-owner@example.com",
    description: str | None = DESCRIPTION,
) -> str:
    async with session_factory() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one()
        job = JobPosting(
            user_id=user.id,
            source_channel="manual_paste",
            title="Senior ML Engineer",
            company_name="Acme Corp",
            remote_type="remote",
            salary_min=150_000,
            salary_max=190_000,
            salary_currency="USD",
            description_text=description,
        )
        db.add(job)
        await db.commit()
        return str(job.id)


async def _add_skill(client: AsyncClient, headers: dict[str, str], name: str) -> None:
    created = await client.post("/profile/skills", headers=headers, json={"name": name})
    assert created.status_code == 201, created.text
    version = await client.post(
        f"/profile/skills/{created.json()['id']}/versions",
        headers=headers,
        json={"level": "advanced", "evidence": f"Built and shipped systems using {name}."},
    )
    assert version.status_code == 201, version.text


async def _match(client: AsyncClient, headers: dict[str, str], job_id: str) -> dict:
    started = await client.post(f"/career/jobs/{job_id}/match", headers=headers)
    assert started.status_code == 202
    job = await client.get(f"/career/jobs/{job_id}", headers=headers)
    assert job.status_code == 200
    return job.json()["match"]


async def test_match_scores_against_profile_with_evidence(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_llm(monkeypatch, _FakeLLM())
    await _add_skill(client, auth_headers, "Python")
    await client.post(
        "/profile/experience",
        headers=auth_headers,
        json={
            "company": "Old Co",
            "title": "Engineer",
            "start_date": "2018-01-01",
            "end_date": "2024-01-01",
        },
    )
    job_id = await _make_job(session_factory)

    match = await _match(client, auth_headers, job_id)

    assert match["status"] == "completed"
    assert match["is_stale"] is False
    components = {c["key"]: c for c in match["components"]}
    # Python exact, TensorFlow missing -> 50% of required skills.
    assert components["required_skills"]["fraction"] == 0.5
    skill_details = {d["requirement"]: d for d in components["required_skills"]["details"]}
    assert skill_details["Python"]["match_type"] == "exact"
    assert skill_details["Python"]["evidence"] == "Built and shipped systems using Python."
    assert skill_details["TensorFlow"]["match_type"] == "missing"
    assert components["experience"]["status"] == "assessed"  # 6y >= 3y
    assert components["experience"]["fraction"] == 1.0
    # No preferences set, so salary / work mode / industry can't be judged.
    assert components["salary"]["status"] == "not_assessed"
    # Skills (35) + preferred skills (10) + experience (20) = 65 measurable.
    assert match["assessed_weight"] == 65
    assert match["low_confidence"] is False
    assert match["score_percent"] is not None
    assert match["deal_breaker_check"] == "none_set"


async def test_sparse_match_is_flagged_low_confidence(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_llm(
        monkeypatch,
        _FakeLLM(
            requirements={
                "required_skills": [
                    {"name": "Python", "quote": "strong Python and TensorFlow skills"}
                ],
                "preferred_skills": [],
            }
        ),
    )
    await _add_skill(client, auth_headers, "Python")
    job_id = await _make_job(session_factory)

    match = await _match(client, auth_headers, job_id)

    assert match["assessed_weight"] == 35
    assert match["low_confidence"] is True
    assert match["score_percent"] == 100  # the 35 measurable points are all earned...
    assert any("Years of experience" in u for u in match["uncertainties"])  # ...but say so


async def test_match_goes_stale_when_profile_changes(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_llm(monkeypatch, _FakeLLM())
    await _add_skill(client, auth_headers, "Python")
    job_id = await _make_job(session_factory)
    assert (await _match(client, auth_headers, job_id))["is_stale"] is False

    await _add_skill(client, auth_headers, "TensorFlow")

    job = await client.get(f"/career/jobs/{job_id}", headers=auth_headers)
    assert job.json()["match"]["is_stale"] is True
    listed = await client.get("/career/jobs", headers=auth_headers)
    assert listed.json()[0]["match"]["is_stale"] is True

    # Re-matching against the new profile clears it, and now finds both skills.
    fresh = await _match(client, auth_headers, job_id)
    assert fresh["is_stale"] is False
    required = next(c for c in fresh["components"] if c["key"] == "required_skills")
    assert required["fraction"] == 1.0


async def test_llm_outage_records_a_failed_match_not_a_guess(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_llm(monkeypatch, _FakeLLM(fail_requirements=True))
    await _add_skill(client, auth_headers, "Python")
    job_id = await _make_job(session_factory)

    match = await _match(client, auth_headers, job_id)

    assert match["status"] == "failed"
    assert "503" in match["error"]
    assert match["score_percent"] is None


async def test_posting_without_description_fails_with_actionable_message(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_llm(monkeypatch, _FakeLLM())
    job_id = await _make_job(session_factory, description=None)

    match = await _match(client, auth_headers, job_id)

    assert match["status"] == "failed"
    assert "paste the full posting" in match["error"]


async def test_deal_breaker_hit_is_reported_with_its_quote(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_llm(
        monkeypatch,
        _FakeLLM(
            hits=[
                {"deal_breaker": "weekend on-call", "quote": "On-call weekends are required"},
                {"deal_breaker": "relocation", "quote": "must relocate"},  # not in posting
            ]
        ),
    )
    await _add_skill(client, auth_headers, "Python")
    await client.put(
        "/profile/preferences",
        headers=auth_headers,
        json={"deal_breakers": "no weekend on-call; no relocation"},
    )
    job_id = await _make_job(session_factory)

    match = await _match(client, auth_headers, job_id)

    assert match["deal_breaker_check"] == "checked"
    assert match["deal_breaker_hits"] == [
        {"deal_breaker": "weekend on-call", "quote": "On-call weekends are required"}
    ]


async def test_failed_deal_breaker_check_is_flagged_unavailable_not_clear(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_llm(monkeypatch, _FakeLLM(fail_deal_breakers=True))
    await _add_skill(client, auth_headers, "Python")
    await client.put(
        "/profile/preferences", headers=auth_headers, json={"deal_breakers": "no on-call"}
    )
    job_id = await _make_job(session_factory)

    match = await _match(client, auth_headers, job_id)

    assert match["status"] == "completed"  # the score itself is still valid
    assert match["deal_breaker_check"] == "unavailable"
    assert match["deal_breaker_hits"] == []
    assert any("deal-breakers could not be checked" in u for u in match["uncertainties"])


async def test_similar_skill_gets_labeled_partial_credit(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vectors = {
        "TensorFlow": [1.0, 0.0],
        "Kubernetes": [0.0, 1.0],
        "PyTorch": [0.95, 0.31],  # cosine with TensorFlow ~ 0.95: similar
        "Python": [0.0, 0.0],
    }

    async def fake_embed(texts: list[str], *, input_type: str = "document"):  # type: ignore[no-untyped-def]
        # Profile indexing calls this too, with longer texts; only bare skill names matter here.
        return [vectors.get(t, [0.0, 0.0]) for t in texts]

    monkeypatch.setattr("app.profile.embeddings.embed_texts", fake_embed)
    _use_llm(monkeypatch, _FakeLLM())
    await _add_skill(client, auth_headers, "Python")
    await _add_skill(client, auth_headers, "PyTorch")
    job_id = await _make_job(session_factory)

    match = await _match(client, auth_headers, job_id)

    required = next(c for c in match["components"] if c["key"] == "required_skills")
    details = {d["requirement"]: d for d in required["details"]}
    assert details["TensorFlow"]["match_type"] == "similar"
    assert details["TensorFlow"]["profile_skill"] == "PyTorch"
    assert required["fraction"] == 0.75  # Python 1.0 + TensorFlow 0.5, over 2


async def test_unavailable_embeddings_are_disclosed(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_embeddings(texts: list[str], *, input_type: str = "document"):  # type: ignore[no-untyped-def]
        return None

    monkeypatch.setattr("app.profile.embeddings.embed_texts", no_embeddings)
    _use_llm(monkeypatch, _FakeLLM())
    await _add_skill(client, auth_headers, "Python")
    job_id = await _make_job(session_factory)

    match = await _match(client, auth_headers, job_id)

    assert match["status"] == "completed"
    assert any("Similar-skill matching was unavailable" in u for u in match["uncertainties"])


async def test_cannot_match_another_users_job(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # Registration is closed once an owner exists, so the second user is created directly.
    async with session_factory() as db:
        db.add(User(email="other@example.com", hashed_password=hash_password("x-y-z-123456")))
        await db.commit()
    job_id = await _make_job(session_factory, email="other@example.com")

    response = await client.post(f"/career/jobs/{job_id}/match", headers=auth_headers)

    assert response.status_code == 404


async def _seed_running_match(
    session_factory: async_sessionmaker[AsyncSession], job_id: str, *, age: timedelta
) -> None:
    async with session_factory() as db:
        db.add(
            JobMatch(
                job_posting_id=uuid.UUID(job_id),
                status="running",
                started_at=datetime.now(UTC) - age,
            )
        )
        await db.commit()


async def test_orphaned_running_match_is_reported_failed_not_running_forever(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    job_id = await _make_job(session_factory)
    await _seed_running_match(session_factory, job_id, age=timedelta(minutes=20))

    job = await client.get(f"/career/jobs/{job_id}", headers=auth_headers)

    match = job.json()["match"]
    assert match["status"] == "failed"
    assert "didn't finish" in match["error"]
    listed = await client.get("/career/jobs", headers=auth_headers)
    assert listed.json()[0]["match"]["status"] == "failed"


async def test_recently_started_match_still_reads_as_running(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    job_id = await _make_job(session_factory)
    # Long enough to be slow (Gemini retries), well short of the timeout.
    await _seed_running_match(session_factory, job_id, age=timedelta(minutes=4))

    job = await client.get(f"/career/jobs/{job_id}", headers=auth_headers)

    assert job.json()["match"]["status"] == "running"


async def test_rematching_a_stalled_match_recovers(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_llm(monkeypatch, _FakeLLM())
    await _add_skill(client, auth_headers, "Python")
    job_id = await _make_job(session_factory)
    await _seed_running_match(session_factory, job_id, age=timedelta(minutes=20))

    match = await _match(client, auth_headers, job_id)

    assert match["status"] == "completed"
