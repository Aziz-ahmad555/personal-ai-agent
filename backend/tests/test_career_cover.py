"""Cover letters through the API, with an LLM that misbehaves on purpose: it quotes the posting to
claim skills the user lacks, invents numbers, and cites nothing. Every such sentence must be
dropped and reported, while honest cited sentences reach the user as paragraphs to accept,
reject, or edit."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.models import AuditLog
from app.auth.security import hash_password
from app.career import cover_service
from app.career.models import CoverLetter, JobMatch, JobPosting
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
    def __init__(self, paragraphs: list[dict] | None = None, *, fail: bool = False) -> None:
        self._paragraphs = paragraphs or []
        self._fail = fail

    async def generate_structured(self, **kwargs: object) -> dict:
        if self._fail:
            raise LLMError("Gemini call failed: 503 UNAVAILABLE")
        assert kwargs["schema_name"] == "draft_cover_letter", "requirements re-extracted"
        return {"paragraphs": self._paragraphs}


def _use_llm(monkeypatch: pytest.MonkeyPatch, llm: _FakeLLM) -> None:
    monkeypatch.setattr(cover_service, "get_llm_provider", lambda settings: llm)


async def _setup_profile(
    client: AsyncClient,
    headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> dict[str, str]:
    await client.put(
        "/profile",
        headers=headers,
        json={"headline": "ML/AI Engineer", "summary": SUMMARY, "location": "Lahore"},
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
    description: str | None = DESCRIPTION,
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


async def _draft(client: AsyncClient, headers: dict[str, str], job_id: str) -> dict:
    started = await client.post(f"/career/jobs/{job_id}/cover-letter", headers=headers)
    assert started.status_code == 202
    fetched = await client.get(f"/career/jobs/{job_id}/cover-letter", headers=headers)
    assert fetched.status_code == 200, fetched.text
    return fetched.json()


def _framing(text: str) -> dict:
    return {"text": text, "kind": "framing", "supports": []}


def _fact(text: str, *supports: dict) -> dict:
    return {"text": text, "kind": "fact", "supports": list(supports)}


def _misbehaving_letter(exp_a: str) -> list[dict]:
    role_quote = {"type": "posting_quote", "ref": "ML Engineer at Acme Corp"}
    exp = {"type": "profile_experience", "ref": f"exp:{exp_a}"}
    return [
        {
            "role": "opening",
            "sentences": [
                _fact("I am writing to apply for the ML Engineer role at Acme Corp.", role_quote),
                _framing("Thank you for considering my application."),
            ],
        },
        {
            "role": "body",
            "sentences": [
                # Honest.
                _fact(
                    "At Vaultic I built a fraud detection web application using Flask, "
                    "SQLAlchemy and XGBoost.",
                    exp,
                ),
                # Quotes the posting to claim a skill the user lacks.
                _fact(
                    "I also have deep Kubernetes experience.",
                    {"type": "posting_quote", "ref": "Kubernetes experience"},
                ),
                # Invents a number.
                _fact("I led a team of 12 engineers there.", exp),
                # Cites nothing.
                _fact("I am a world-class engineer."),
            ],
        },
        {
            # Every sentence unsupported: the whole paragraph must vanish.
            "role": "body",
            "sentences": [_fact("I have led migrations to Kubernetes.", exp)],
        },
        {
            "role": "closing",
            "sentences": [_framing("I look forward to hearing from you.")],
        },
    ]


async def test_honest_sentences_survive_and_fabricated_ones_are_dropped_and_reported(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = await _setup_profile(client, auth_headers, session_factory)
    _use_llm(monkeypatch, _FakeLLM(_misbehaving_letter(ids["a"])))
    job_id = await _make_job(session_factory)

    letter = await _draft(client, auth_headers, job_id)

    assert letter["status"] == "completed"
    assert [p["role"] for p in letter["paragraphs"]] == ["opening", "body", "closing"]
    body = letter["paragraphs"][1]
    assert body["text"] == (
        "At Vaultic I built a fraud detection web application using Flask, SQLAlchemy and XGBoost."
    )
    support = body["sentences"][0]["supports"][0]
    assert support["label"] == "Vaultic — University"
    assert support["excerpt"] == EXP_A_TEXT  # the evidence the sentence was checked against

    reasons = {d["sentence"]: d["reason"] for d in letter["dropped"]}
    assert "'Kubernetes'" in reasons["I also have deep Kubernetes experience."]
    assert "number(s)" in reasons["I led a team of 12 engineers there."]
    assert "cites nothing" in reasons["I am a world-class engineer."]
    assert "'Kubernetes'" in reasons["I have led migrations to Kubernetes."]

    gaps = {g["skill"]: g["reason"] for g in letter["gaps"]}
    assert gaps["Kubernetes"] == "it isn't in your profile"
    assert gaps["Docker"] == "it's in your profile, but with no evidence recorded"

    # Nothing accepted yet, so there is no letter — and the unsupported claims appear nowhere.
    assert letter["counts"] == {"accepted": 0, "rejected": 0, "pending": 3}
    assert letter["preview_text"] == ""
    assert "Kubernetes" not in str(letter["paragraphs"])


async def test_accepted_paragraphs_build_the_letter_and_rejected_ones_stay_out(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = await _setup_profile(client, auth_headers, session_factory)
    _use_llm(monkeypatch, _FakeLLM(_misbehaving_letter(ids["a"])))
    job_id = await _make_job(session_factory)
    letter = await _draft(client, auth_headers, job_id)
    opening, body, closing = letter["paragraphs"]
    base = f"/career/cover-letters/{letter['id']}/paragraphs"

    for paragraph, decision in ((opening, "accepted"), (body, "accepted"), (closing, "rejected")):
        response = await client.post(
            f"{base}/{paragraph['id']}/decision", headers=auth_headers, json={"decision": decision}
        )
        assert response.status_code == 200

    preview = response.json()["preview_text"]
    assert preview.startswith("Dear Hiring Team,\n\nI am writing to apply")
    assert "At Vaultic I built a fraud detection" in preview
    assert "look forward to hearing" not in preview  # rejected
    assert preview.endswith("Sincerely,\nAziz Ahmad\n")
    assert response.json()["counts"] == {"accepted": 2, "rejected": 1, "pending": 0}


async def test_an_edited_paragraph_is_flagged_as_not_fact_checked_and_can_be_restored(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = await _setup_profile(client, auth_headers, session_factory)
    _use_llm(monkeypatch, _FakeLLM(_misbehaving_letter(ids["a"])))
    job_id = await _make_job(session_factory)
    letter = await _draft(client, auth_headers, job_id)
    opening = letter["paragraphs"][0]
    url = f"/career/cover-letters/{letter['id']}/paragraphs/{opening['id']}"
    await client.post(f"{url}/decision", headers=auth_headers, json={"decision": "accepted"})

    edited = await client.patch(
        url, headers=auth_headers, json={"text": "  My own opening, in my own words.  "}
    )

    body = edited.json()
    paragraph = body["paragraphs"][0]
    assert paragraph["is_edited"] is True
    assert paragraph["edited_text"] == "My own opening, in my own words."
    assert paragraph["text"] == opening["text"]  # the fact-checked original is kept
    assert "My own opening, in my own words." in body["preview_text"]

    export_url = f"/career/cover-letters/{letter['id']}/export"
    export = (await client.get(export_url, headers=auth_headers)).json()
    assert export["edited"] == 1
    assert "My own opening" in export["text"]

    restored = await client.patch(url, headers=auth_headers, json={"text": None})
    assert restored.json()["paragraphs"][0]["is_edited"] is False
    assert opening["text"] in restored.json()["preview_text"]

    async with session_factory() as db:
        edited_action = "career.cover_letter.paragraph_edited"
        entries = (
            (await db.execute(select(AuditLog).where(AuditLog.action == edited_action)))
            .scalars()
            .all()
        )
    assert len(entries) == 2
    assert all("own words" not in str(e.evidence) + e.summary for e in entries)  # text isn't copied


async def test_export_needs_an_accepted_paragraph_and_is_audited(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = await _setup_profile(client, auth_headers, session_factory)
    _use_llm(monkeypatch, _FakeLLM(_misbehaving_letter(ids["a"])))
    job_id = await _make_job(session_factory)
    letter = await _draft(client, auth_headers, job_id)
    export_url = f"/career/cover-letters/{letter['id']}/export"

    nothing = await client.get(export_url, headers=auth_headers)
    assert nothing.status_code == 409
    assert "Accept at least one paragraph" in nothing.json()["detail"]

    await client.post(
        f"/career/cover-letters/{letter['id']}/paragraphs/{letter['paragraphs'][1]['id']}/decision",
        headers=auth_headers,
        json={"decision": "accepted"},
    )
    export = await client.get(export_url, headers=auth_headers)

    assert export.status_code == 200
    body = export.json()
    assert body["filename"] == "cover-letter-acme-corp-ml-engineer.txt"
    assert (body["accepted"], body["pending"], body["rejected"], body["edited"]) == (1, 2, 0, 0)
    async with session_factory() as db:
        actions = set((await db.execute(select(AuditLog.action))).scalars().all())
    assert {"career.cover_letter.drafted", "career.cover_letter.exported"} <= actions


async def test_a_body_paragraph_with_no_verified_facts_is_dropped(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = await _setup_profile(client, auth_headers, session_factory)
    exp = {"type": "profile_experience", "ref": f"exp:{ids['a']}"}
    _use_llm(
        monkeypatch,
        _FakeLLM(
            [
                {"role": "body", "sentences": [_framing("I am a great fit.")]},
                {
                    "role": "body",
                    "sentences": [_fact("I built a fraud detection application in Flask.", exp)],
                },
            ]
        ),
    )
    job_id = await _make_job(session_factory)

    letter = await _draft(client, auth_headers, job_id)

    assert len(letter["paragraphs"]) == 1
    reasons = {d["sentence"]: d["reason"] for d in letter["dropped"]}
    assert reasons["I am a great fit."] == "a body paragraph with no verified facts"


async def test_a_letter_with_no_surviving_facts_fails_clearly(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _setup_profile(client, auth_headers, session_factory)
    _use_llm(
        monkeypatch,
        _FakeLLM([{"role": "body", "sentences": [_fact("I invented all of this.")]}]),
    )
    job_id = await _make_job(session_factory)

    letter = await _draft(client, auth_headers, job_id)

    assert letter["status"] == "failed"
    assert "stays within what your profile supports" in letter["error"]
    assert letter["paragraphs"] == []


async def test_llm_outage_and_missing_inputs_are_clear_failures(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_llm(monkeypatch, _FakeLLM())
    empty = await _draft(client, auth_headers, await _make_job(session_factory))
    assert empty["status"] == "failed"
    assert "nothing to write a letter from" in empty["error"]

    await _setup_profile(client, auth_headers, session_factory)
    no_description = await _draft(
        client, auth_headers, await _make_job(session_factory, description=None)
    )
    assert "paste the full posting" in no_description["error"]

    _use_llm(monkeypatch, _FakeLLM(fail=True))
    outage = await _draft(client, auth_headers, await _make_job(session_factory))
    assert outage["status"] == "failed"
    assert "503" in outage["error"]


async def test_a_draft_goes_stale_when_the_profile_changes_and_regenerating_resets_it(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = await _setup_profile(client, auth_headers, session_factory)
    _use_llm(monkeypatch, _FakeLLM(_misbehaving_letter(ids["a"])))
    job_id = await _make_job(session_factory)
    first = await _draft(client, auth_headers, job_id)
    assert first["is_stale"] is False
    await client.post(
        f"/career/cover-letters/{first['id']}/paragraphs/{first['paragraphs'][0]['id']}/decision",
        headers=auth_headers,
        json={"decision": "accepted"},
    )

    await client.put("/profile", headers=auth_headers, json={"summary": "A rewritten summary."})
    stale = await client.get(f"/career/jobs/{job_id}/cover-letter", headers=auth_headers)
    assert stale.json()["is_stale"] is True

    second = await _draft(client, auth_headers, job_id)
    assert second["id"] == first["id"]  # one draft per job
    assert second["is_stale"] is False
    assert second["counts"] == {"accepted": 0, "rejected": 0, "pending": 3}


async def test_an_orphaned_run_is_reported_failed_not_running_forever(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    job_id = await _make_job(session_factory)
    async with session_factory() as db:
        user = (await db.execute(select(User).where(User.email == OWNER))).scalar_one()
        db.add(
            CoverLetter(
                user_id=user.id,
                job_posting_id=uuid.UUID(job_id),
                status="running",
                started_at=datetime.now(UTC) - timedelta(minutes=20),
            )
        )
        await db.commit()

    letter = (await client.get(f"/career/jobs/{job_id}/cover-letter", headers=auth_headers)).json()

    assert letter["status"] == "failed"
    assert "didn't finish" in letter["error"]


async def test_inputs_are_validated(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = await _setup_profile(client, auth_headers, session_factory)
    _use_llm(monkeypatch, _FakeLLM(_misbehaving_letter(ids["a"])))
    job_id = await _make_job(session_factory)
    letter = await _draft(client, auth_headers, job_id)
    url = f"/career/cover-letters/{letter['id']}/paragraphs/{letter['paragraphs'][0]['id']}"

    bad_decision = await client.post(
        f"{url}/decision", headers=auth_headers, json={"decision": "maybe"}
    )
    too_long = await client.patch(url, headers=auth_headers, json={"text": "x" * 4001})
    unknown = await client.post(
        f"/career/cover-letters/{letter['id']}/paragraphs/{uuid.uuid4()}/decision",
        headers=auth_headers,
        json={"decision": "accepted"},
    )

    assert bad_decision.status_code == 422
    assert too_long.status_code == 422
    assert unknown.status_code == 404


async def test_other_users_jobs_and_drafts_are_invisible_and_delete_works(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with session_factory() as db:
        other = User(email="other@example.com", hashed_password=hash_password("x-y-z-123456"))
        db.add(other)
        await db.commit()
        job = JobPosting(user_id=other.id, source_channel="manual_paste", title="T")
        db.add(job)
        await db.commit()
        foreign = CoverLetter(user_id=other.id, job_posting_id=job.id, status="completed")
        db.add(foreign)
        await db.commit()
        foreign_job, foreign_id = str(job.id), str(foreign.id)

    job_url = f"/career/jobs/{foreign_job}/cover-letter"
    assert await _code(client, "post", job_url, auth_headers) == 404
    assert await _code(client, "get", job_url, auth_headers) == 404
    export_url = f"/career/cover-letters/{foreign_id}/export"
    assert await _code(client, "get", export_url, auth_headers) == 404
    assert await _code(client, "delete", f"/career/cover-letters/{foreign_id}", auth_headers) == 404

    ids = await _setup_profile(client, auth_headers, session_factory)
    _use_llm(monkeypatch, _FakeLLM(_misbehaving_letter(ids["a"])))
    job_id = await _make_job(session_factory)
    assert await _code(client, "get", f"/career/jobs/{job_id}/cover-letter", auth_headers) == 404
    letter = await _draft(client, auth_headers, job_id)

    delete_url = f"/career/cover-letters/{letter['id']}"
    assert await _code(client, "delete", delete_url, auth_headers) == 204
    assert await _code(client, "get", f"/career/jobs/{job_id}/cover-letter", auth_headers) == 404
    assert await _code(client, "get", f"/career/jobs/{job_id}", auth_headers) == 200
