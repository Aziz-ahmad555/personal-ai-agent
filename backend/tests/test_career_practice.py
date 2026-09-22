"""Interview practice through the API, with an LLM that misbehaves on purpose: it proposes a
question grounded in a requirement that doesn't exist, and writes feedback that reaches for facts
never in the question's grounding or the candidate's own answer. Every such item must be dropped
(questions) or fall back to an honest, unverified message (feedback), while grounded questions and
verified feedback reach the user."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.models import AuditLog
from app.auth.security import hash_password
from app.career import practice_service
from app.career.models import Application, JobMatch, JobPosting, PracticeSession
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
SUMMARY = "Engineer who builds machine learning systems and APIs."


class _FakeLLM:
    def __init__(
        self,
        *,
        questions: list[dict] | None = None,
        feedback: list[dict] | None = None,
        fail_questions: bool = False,
        fail_feedback: bool = False,
    ) -> None:
        self._questions = questions if questions is not None else []
        self._feedback = feedback if feedback is not None else []
        self._fail_questions = fail_questions
        self._fail_feedback = fail_feedback

    async def generate_structured(self, **kwargs: object) -> dict:
        schema = kwargs["schema_name"]
        if schema == "generate_practice_questions":
            if self._fail_questions:
                raise LLMError("Gemini call failed: 503 UNAVAILABLE")
            return {"questions": self._questions}
        if schema == "generate_practice_feedback":
            if self._fail_feedback:
                raise LLMError("Gemini call failed: 429 RESOURCE_EXHAUSTED")
            return {"feedback": self._feedback}
        raise AssertionError(f"unexpected schema {schema!r}")


def _use_llm(monkeypatch: pytest.MonkeyPatch, llm: _FakeLLM) -> None:
    monkeypatch.setattr(practice_service, "get_llm_provider", lambda settings: llm)


def _question(text: str, category: str, ref_type: str, ref: str) -> dict:
    return {"text": text, "category": category, "ref_type": ref_type, "ref": ref}


def _feedback_item(question_id: str, verdict: str, rationale: str) -> dict:
    return {"question_id": question_id, "verdict": verdict, "rationale": rationale}


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
    created = await client.post(
        "/profile/experience",
        headers=headers,
        json={
            "company": "University",
            "title": "Vaultic",
            "start_date": "2026-03-01",
            "description": EXP_A_TEXT,
        },
    )
    ids["a"] = created.json()["id"]
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
    return ids


async def _make_job(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    email: str = OWNER,
    description: str | None = DESCRIPTION,
    match_status: str | None = "completed",
    requirements: dict | None = MATCH_REQUIREMENTS,
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
        if match_status is not None:
            db.add(
                JobMatch(
                    job_posting_id=job.id,
                    status=match_status,
                    score_percent=50 if match_status == "completed" else None,
                    assessed_weight=50,
                    low_confidence=False,
                    requirements=requirements,
                )
            )
        await db.commit()
        return str(job.id)


async def _code(client: AsyncClient, method: str, path: str, headers: dict[str, str]) -> int:
    return (await getattr(client, method)(path, headers=headers)).status_code


async def _start(
    client: AsyncClient, headers: dict[str, str], job_id: str, *, application_id: str | None = None
):
    body = {"application_id": application_id} if application_id else {}
    return await client.post(f"/career/jobs/{job_id}/practice-sessions", headers=headers, json=body)


async def _start_and_fetch(
    client: AsyncClient, headers: dict[str, str], job_id: str, *, application_id: str | None = None
) -> dict:
    started = await _start(client, headers, job_id, application_id=application_id)
    assert started.status_code == 202, started.text
    listed = await client.get(f"/career/jobs/{job_id}/practice-sessions", headers=headers)
    assert listed.status_code == 200
    session_id = listed.json()[0]["id"]
    detail = await client.get(f"/career/practice-sessions/{session_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    return detail.json()


def _grounded_questions(ids: dict[str, str]) -> list[dict]:
    return [
        _question(
            "How have you used Python day to day?", "technical", "posting_requirement", "Python"
        ),
        _question(
            "Tell me about the fraud detection app you built.",
            "behavioral",
            "profile_experience",
            f"exp:{ids['a']}",
        ),
        _question(
            "Describe a FastAPI project you shipped.", "technical", "profile_skill", "FastAPI"
        ),
        # Ungrounded: no such requirement exists.
        _question("How would you use Rust here?", "technical", "posting_requirement", "Rust"),
    ]


async def test_grounded_questions_survive_and_ungrounded_ones_are_dropped(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = await _setup_profile(client, auth_headers, session_factory)
    _use_llm(monkeypatch, _FakeLLM(questions=_grounded_questions(ids)))
    job_id = await _make_job(session_factory)

    session = await _start_and_fetch(client, auth_headers, job_id)

    assert session["status"] == "ready_for_answers"
    assert len(session["questions"]) == 3
    by_ref_type = {q["ref_type"]: q for q in session["questions"]}
    assert by_ref_type["posting_requirement"]["ref_name"] == "Python"
    assert by_ref_type["posting_requirement"]["ref_excerpt"] == "strong Python skills"
    assert by_ref_type["profile_experience"]["ref_name"] == "Vaultic — University"
    assert by_ref_type["profile_experience"]["ref_excerpt"] == EXP_A_TEXT
    assert by_ref_type["profile_skill"]["ref_name"] == "FastAPI"

    reasons = {d["question"]: d["reason"] for d in session["dropped"]}
    assert "Rust" in reasons["How would you use Rust here?"]
    assert session["counts"] == {
        "addressed": 0,
        "partially_addressed": 0,
        "missed": 0,
        "unclear": 0,
        "unanswered": 3,
    }


async def test_full_flow_answers_get_verified_feedback_and_unverifiable_feedback_falls_back(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = await _setup_profile(client, auth_headers, session_factory)
    _use_llm(monkeypatch, _FakeLLM(questions=_grounded_questions(ids)))
    job_id = await _make_job(session_factory)
    session = await _start_and_fetch(client, auth_headers, job_id)
    python_q, exp_q, skill_q = (
        next(q for q in session["questions"] if q["ref_type"] == "posting_requirement"),
        next(q for q in session["questions"] if q["ref_type"] == "profile_experience"),
        next(q for q in session["questions"] if q["ref_type"] == "profile_skill"),
    )

    feedback = [
        # Honest: only reuses words from the requirement's quote and the candidate's own answer.
        _feedback_item(
            python_q["id"],
            "addressed",
            "The candidate describes using Python skills directly, matching the requirement.",
        ),
        # Fabricated: claims a number and a system ("Kubernetes") the answer never mentions.
        _feedback_item(
            exp_q["id"],
            "addressed",
            "The candidate led 12 engineers and deployed it on Kubernetes.",
        ),
    ]
    _use_llm(monkeypatch, _FakeLLM(feedback=feedback))
    submitted = await client.patch(
        f"/career/practice-sessions/{session['id']}/answers",
        headers=auth_headers,
        json={
            "answers": [
                {
                    "question_id": python_q["id"],
                    "answer_text": "I used Python skills daily at work.",
                },
                {
                    "question_id": exp_q["id"],
                    "answer_text": "At Vaultic I built the fraud detection app end to end.",
                },
                # skill_q left unanswered on purpose.
            ]
        },
    )
    assert submitted.status_code == 202, submitted.text

    final = (
        await client.get(f"/career/practice-sessions/{session['id']}", headers=auth_headers)
    ).json()

    assert final["status"] == "completed"
    by_id = {q["id"]: q for q in final["questions"]}
    assert by_id[python_q["id"]]["verdict"] == "addressed"
    assert "Python" in by_id[python_q["id"]]["feedback_text"]
    assert by_id[exp_q["id"]]["verdict"] == "unclear"
    assert (
        by_id[exp_q["id"]]["feedback_text"]
        == "Feedback couldn't be verified against your answer."
    )
    assert by_id[skill_q["id"]]["verdict"] == "missed"
    assert by_id[skill_q["id"]]["feedback_text"] == "No answer was given."
    assert final["counts"] == {
        "addressed": 1,
        "partially_addressed": 0,
        "missed": 0,
        "unclear": 1,
        "unanswered": 1,
    }


async def test_starting_a_session_requires_a_completed_match(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    no_match = await _make_job(session_factory, match_status=None)
    running_match = await _make_job(session_factory, match_status="running")

    for job_id in (no_match, running_match):
        response = await _start(client, auth_headers, job_id)
        assert response.status_code == 409
        assert "Score this job's match first" in response.json()["detail"]


async def test_only_one_active_session_per_job_at_a_time(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = await _setup_profile(client, auth_headers, session_factory)
    _use_llm(monkeypatch, _FakeLLM(questions=_grounded_questions(ids)))
    job_id = await _make_job(session_factory)
    await _start_and_fetch(client, auth_headers, job_id)  # now ready_for_answers: still active

    blocked = await _start(client, auth_headers, job_id)
    assert blocked.status_code == 409
    assert "already in progress" in blocked.json()["detail"]


async def test_application_id_must_belong_to_the_same_job_and_user(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = await _setup_profile(client, auth_headers, session_factory)
    _use_llm(monkeypatch, _FakeLLM(questions=_grounded_questions(ids)))
    job_id = await _make_job(session_factory)
    other_job_id = await _make_job(session_factory, description="A different posting entirely.")

    async with session_factory() as db:
        user = (await db.execute(select(User).where(User.email == OWNER))).scalar_one()
        application = Application(user_id=user.id, job_posting_id=uuid.UUID(other_job_id))
        db.add(application)
        await db.commit()
        mismatched_application_id = str(application.id)

    response = await _start(
        client, auth_headers, job_id, application_id=mismatched_application_id
    )
    assert response.status_code == 422
    assert "isn't linked to this job" in response.json()["detail"]

    response = await _start(client, auth_headers, job_id, application_id=str(uuid.uuid4()))
    assert response.status_code == 422


async def test_llm_outage_during_question_generation_is_a_clear_failure(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _setup_profile(client, auth_headers, session_factory)
    _use_llm(monkeypatch, _FakeLLM(fail_questions=True))
    job_id = await _make_job(session_factory)

    session = await _start_and_fetch(client, auth_headers, job_id)

    assert session["status"] == "failed"
    assert "503" in session["error"]


async def test_missing_profile_or_requirements_are_clear_failures(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_llm(monkeypatch, _FakeLLM())
    empty_profile_job = await _make_job(session_factory)
    empty = await _start_and_fetch(client, auth_headers, empty_profile_job)
    assert empty["status"] == "failed"
    assert "nothing to ground questions in" in empty["error"]

    await _setup_profile(client, auth_headers, session_factory)
    no_requirements_job = await _make_job(
        session_factory,
        requirements={"required_skills": [], "preferred_skills": []},
        description="Another posting.",
    )
    no_reqs = await _start_and_fetch(client, auth_headers, no_requirements_job)
    assert no_reqs["status"] == "failed"
    assert "nothing to ask about" in no_reqs["error"]


async def test_answers_can_be_resubmitted_after_a_failed_feedback_run(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = await _setup_profile(client, auth_headers, session_factory)
    _use_llm(monkeypatch, _FakeLLM(questions=_grounded_questions(ids)))
    job_id = await _make_job(session_factory)
    session = await _start_and_fetch(client, auth_headers, job_id)
    python_q = next(q for q in session["questions"] if q["ref_type"] == "posting_requirement")

    _use_llm(monkeypatch, _FakeLLM(fail_feedback=True))
    answer_body = {
        "answers": [{"question_id": python_q["id"], "answer_text": "I use Python every day."}]
    }
    first_attempt = await client.patch(
        f"/career/practice-sessions/{session['id']}/answers", headers=auth_headers, json=answer_body
    )
    assert first_attempt.status_code == 202
    failed = (
        await client.get(f"/career/practice-sessions/{session['id']}", headers=auth_headers)
    ).json()
    assert failed["status"] == "failed"
    assert "429" in failed["error"]
    # The answer already given wasn't lost.
    assert failed["questions"][0]["answer_text"] is not None

    _use_llm(
        monkeypatch,
        _FakeLLM(
            feedback=[
                _feedback_item(
                    python_q["id"], "addressed", "The candidate mentions using Python daily."
                )
            ]
        ),
    )
    retried = await client.patch(
        f"/career/practice-sessions/{session['id']}/answers", headers=auth_headers, json=answer_body
    )
    assert retried.status_code == 202
    final = (
        await client.get(f"/career/practice-sessions/{session['id']}", headers=auth_headers)
    ).json()
    assert final["status"] == "completed"


async def test_submitting_answers_is_validated(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = await _setup_profile(client, auth_headers, session_factory)
    _use_llm(monkeypatch, _FakeLLM(questions=_grounded_questions(ids)))
    job_id = await _make_job(session_factory)
    session = await _start_and_fetch(client, auth_headers, job_id)

    unknown_question = await client.patch(
        f"/career/practice-sessions/{session['id']}/answers",
        headers=auth_headers,
        json={"answers": [{"question_id": str(uuid.uuid4()), "answer_text": "x"}]},
    )
    assert unknown_question.status_code == 422

    too_long = await client.patch(
        f"/career/practice-sessions/{session['id']}/answers",
        headers=auth_headers,
        json={
            "answers": [
                {"question_id": session["questions"][0]["id"], "answer_text": "x" * 4001}
            ]
        },
    )
    assert too_long.status_code == 422

    # Not ready: still questions_running (no questions generated yet).
    running_job = await _make_job(session_factory, description="Yet another posting.")
    async with session_factory() as db:
        user = (await db.execute(select(User).where(User.email == OWNER))).scalar_one()
        stuck = PracticeSession(
            user_id=user.id,
            job_posting_id=uuid.UUID(running_job),
            status="questions_running",
            started_at=datetime.now(UTC),
        )
        db.add(stuck)
        await db.commit()
        stuck_id = str(stuck.id)
    not_ready = await client.patch(
        f"/career/practice-sessions/{stuck_id}/answers", headers=auth_headers, json={"answers": []}
    )
    assert not_ready.status_code == 409


async def test_an_orphaned_run_is_reported_failed_in_either_phase(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    job_id = await _make_job(session_factory)
    async with session_factory() as db:
        user = (await db.execute(select(User).where(User.email == OWNER))).scalar_one()
        stalled_questions = PracticeSession(
            user_id=user.id,
            job_posting_id=uuid.UUID(job_id),
            status="questions_running",
            started_at=datetime.now(UTC) - timedelta(minutes=20),
        )
        stalled_feedback = PracticeSession(
            user_id=user.id,
            job_posting_id=uuid.UUID(job_id),
            status="feedback_running",
            started_at=datetime.now(UTC) - timedelta(minutes=20),
        )
        db.add_all([stalled_questions, stalled_feedback])
        await db.commit()
        ids = (str(stalled_questions.id), str(stalled_feedback.id))

    for session_id in ids:
        response = await client.get(f"/career/practice-sessions/{session_id}", headers=auth_headers)
        assert response.json()["status"] == "failed"
        assert "didn't finish" in response.json()["error"]


async def test_other_users_sessions_are_invisible_and_delete_works(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with session_factory() as db:
        other = User(
            email="other-practice@example.com", hashed_password=hash_password("x-y-z-123456")
        )
        db.add(other)
        await db.commit()
        job = JobPosting(user_id=other.id, source_channel="manual_paste", title="T")
        db.add(job)
        await db.commit()
        foreign = PracticeSession(
            user_id=other.id,
            job_posting_id=job.id,
            status="completed",
            started_at=datetime.now(UTC),
        )
        db.add(foreign)
        await db.commit()
        foreign_job, foreign_id = str(job.id), str(foreign.id)

    jobs_url = f"/career/jobs/{foreign_job}/practice-sessions"
    session_url = f"/career/practice-sessions/{foreign_id}"
    assert await _code(client, "get", jobs_url, auth_headers) == 404
    assert await _code(client, "get", session_url, auth_headers) == 404
    assert await _code(client, "delete", session_url, auth_headers) == 404
    unknown_start = await _start(client, auth_headers, foreign_job)
    assert unknown_start.status_code == 404

    ids = await _setup_profile(client, auth_headers, session_factory)
    _use_llm(monkeypatch, _FakeLLM(questions=_grounded_questions(ids)))
    job_id = await _make_job(session_factory)
    session = await _start_and_fetch(client, auth_headers, job_id)

    delete_url = f"/career/practice-sessions/{session['id']}"
    assert await _code(client, "delete", delete_url, auth_headers) == 204
    assert await _code(client, "get", delete_url, auth_headers) == 404

    async with session_factory() as db:
        actions = set((await db.execute(select(AuditLog.action))).scalars().all())
    assert {
        "career.practice_session.questions_generated",
        "career.practice_session.deleted",
    } <= actions
