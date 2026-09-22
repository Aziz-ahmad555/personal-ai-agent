"""Interview-practice orchestration. Green risk: it reads the user's own profile and a job's
already-verified requirements and writes local questions/feedback — nothing is sent anywhere.
Logged to the audit trail.

Two-phase flow, each phase its own LLM call fact-checked the same discipline as cover letters
and tailored resumes (see app.career.practice_verify):

1. start_session (sync) -> run_question_generation (background): assemble the base resume,
   reuse the job's verified requirements, one LLM call proposing questions, plain-code
   grounding-resolution of every question (an ungrounded one is dropped and reported) -> persist
   for the user to answer.
2. submit_answers (sync, plain code, no LLM) -> run_feedback_generation (background): an
   unanswered question is marked "missed" deterministically, never sent to the LLM; answered
   ones get one LLM call for feedback, each item fact-checked against its own grounding and the
   user's own answer text -> persist.

Unlike JobMatch/TailoredResume/CoverLetter, a job may have many practice sessions (practice is
meant to be repeated) — app.career.practice_router enforces at most one active at a time.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import log_action
from app.career.models import JobMatch, JobPosting, PracticeQuestion, PracticeSession
from app.career.practice_llm import generate_feedback, generate_questions
from app.career.practice_verify import verify_feedback_item, verify_question
from app.career.resume_service import load_base_resume, requirements_for
from app.config import get_settings
from app.logging import get_logger
from app.research.llm import LLMError, get_llm_provider

logger = get_logger(__name__)

# Same reasoning as MATCH_TIMEOUT/TAILOR_TIMEOUT/LETTER_TIMEOUT: a healthy run can take minutes
# under provider overload, but a background task dies with the server, so past this the run is
# presumed dead. Applies to both LLM phases (questions, then again for feedback) — never while
# a session is simply waiting on the user in "ready_for_answers".
PRACTICE_TIMEOUT = timedelta(minutes=10)
STALLED_MESSAGE = (
    "This didn't finish — the server was probably restarted while it was working. Try again."
)
ACTIVE_STATUSES = ("questions_running", "ready_for_answers", "feedback_running")


class PracticeError(RuntimeError):
    """A practice run couldn't finish at all; the message is shown to the user as-is."""


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def is_stalled(session: PracticeSession, *, now: datetime | None = None) -> bool:
    if session.status not in ("questions_running", "feedback_running"):
        return False
    return (now or datetime.now(UTC)) - _as_utc(session.started_at) > PRACTICE_TIMEOUT


async def has_completed_match(db: AsyncSession, job_posting_id: uuid.UUID) -> bool:
    match = (
        await db.execute(select(JobMatch).where(JobMatch.job_posting_id == job_posting_id))
    ).scalar_one_or_none()
    return match is not None and match.status == "completed"


async def get_active_session(
    db: AsyncSession, job_posting_id: uuid.UUID
) -> PracticeSession | None:
    return (
        await db.execute(
            select(PracticeSession).where(
                PracticeSession.job_posting_id == job_posting_id,
                PracticeSession.status.in_(ACTIVE_STATUSES),
            )
        )
    ).scalar_one_or_none()


async def list_sessions(db: AsyncSession, job_posting_id: uuid.UUID) -> list[PracticeSession]:
    return list(
        (
            await db.execute(
                select(PracticeSession)
                .where(PracticeSession.job_posting_id == job_posting_id)
                .order_by(PracticeSession.created_at.desc())
            )
        )
        .scalars()
        .all()
    )


async def load_questions(db: AsyncSession, session_id: uuid.UUID) -> list[PracticeQuestion]:
    return list(
        (
            await db.execute(
                select(PracticeQuestion)
                .where(PracticeQuestion.session_id == session_id)
                .order_by(PracticeQuestion.position)
            )
        )
        .scalars()
        .all()
    )


async def start_session(
    db: AsyncSession,
    job: JobPosting,
    user_id: uuid.UUID,
    *,
    application_id: uuid.UUID | None = None,
) -> PracticeSession:
    session = PracticeSession(
        user_id=user_id,
        job_posting_id=job.id,
        application_id=application_id,
        status="questions_running",
        started_at=datetime.now(UTC),
    )
    db.add(session)
    await db.flush()
    return session


async def run_question_generation(
    db: AsyncSession, session_id: uuid.UUID, *, user_id: uuid.UUID
) -> None:
    session = await db.get(PracticeSession, session_id)
    if session is None:
        logger.warning("career_practice_session_not_found", session_id=str(session_id))
        return
    job = await db.get(JobPosting, session.job_posting_id)
    if job is None:
        logger.warning("career_job_not_found_for_practice", session_id=str(session_id))
        return
    try:
        await _compute_questions(db, job, session, user_id=user_id)
    except (PracticeError, LLMError) as exc:
        await _fail(db, session, str(exc), user_id=user_id)
    except Exception as exc:  # last-resort guardrail: a crash must still resolve the row
        logger.exception("career_practice_questions_crashed", session_id=str(session_id))
        await _fail(db, session, f"Unexpected error: {exc}", user_id=user_id)


async def _fail(
    db: AsyncSession, session: PracticeSession, message: str, *, user_id: uuid.UUID
) -> None:
    session.status = "failed"
    session.error = message
    await db.flush()
    await log_action(
        db,
        user_id=user_id,
        action="career.practice_session.failed",
        risk_level="green",
        summary="Interview practice couldn't finish.",
        resource_type="job_posting",
        resource_id=session.job_posting_id,
        error=message,
    )


async def _compute_questions(
    db: AsyncSession, job: JobPosting, session: PracticeSession, *, user_id: uuid.UUID
) -> None:
    base = await load_base_resume(db, user_id)
    if not (base.has_tailorable_content or base.skills):
        raise PracticeError(
            "Your profile has no summary, work-history descriptions, or evidence-backed skills "
            "yet, so there's nothing to ground questions in. Add some on the Profile page first."
        )

    llm = get_llm_provider(get_settings())
    requirements = await requirements_for(db, job, llm)
    if not requirements:
        raise PracticeError(
            "No requirements could be read from this posting, so there's nothing to ask about. "
            "Paste the full posting and score the match first."
        )

    raw_questions = await generate_questions(
        llm, job_title=job.title, company=job.company_name, requirements=requirements, base=base
    )

    questions: list[PracticeQuestion] = []
    dropped: list[dict[str, str]] = []
    for raw in raw_questions:
        clean, reason = verify_question(raw, requirements=requirements, base=base)
        if clean is None:
            shown = str(raw.get("text", "") if isinstance(raw, dict) else "")
            dropped.append({"question": shown.strip()[:240], "reason": reason or "unverified"})
            continue
        questions.append(
            PracticeQuestion(session_id=session.id, position=len(questions), **clean)
        )

    if not questions:
        raise PracticeError(
            "No practice questions could be grounded in this posting or your profile — every "
            "one the model proposed was discarded. Try scoring the match again, or add more "
            "profile evidence."
        )

    db.add_all(questions)
    session.requirements = requirements
    session.profile_stamp = base.stamp()
    session.dropped = dropped
    session.status = "ready_for_answers"
    session.error = None
    await db.flush()

    await log_action(
        db,
        user_id=user_id,
        action="career.practice_session.questions_generated",
        risk_level="green",
        summary=f"Generated {len(questions)} interview-practice questions.",
        evidence={"questions": len(questions), "discarded_ungrounded": len(dropped)},
        resource_type="job_posting",
        resource_id=job.id,
    )


async def submit_answers(
    db: AsyncSession,
    session: PracticeSession,
    answers: list[Any],
    *,
    user_id: uuid.UUID,
) -> None:
    """Plain code, no LLM: writes the user's own answers. `answers` items need only
    `.question_id` and `.answer_text` attributes (the router's Pydantic schema satisfies this).
    A question left out of `answers`, or resubmitted blank, stays/becomes unanswered."""
    questions = await load_questions(db, session.id)
    by_id = {str(q.id): q for q in questions}
    now = datetime.now(UTC)
    answered_count = 0
    for answer in answers:
        question = by_id.get(str(answer.question_id))
        if question is None:
            raise ValueError(f"Question {answer.question_id} isn't part of this session.")
        text = (answer.answer_text or "").strip()
        question.answer_text = text or None
        question.answered_at = now if text else None
        if text:
            answered_count += 1

    session.status = "feedback_running"
    session.started_at = now
    session.error = None
    await db.flush()

    await log_action(
        db,
        user_id=user_id,
        action="career.practice_session.answers_submitted",
        risk_level="green",
        summary=f"Submitted answers for {answered_count} of {len(questions)} practice questions.",
        resource_type="job_posting",
        resource_id=session.job_posting_id,
    )


async def run_feedback_generation(
    db: AsyncSession, session_id: uuid.UUID, *, user_id: uuid.UUID
) -> None:
    session = await db.get(PracticeSession, session_id)
    if session is None:
        logger.warning("career_practice_session_not_found", session_id=str(session_id))
        return
    questions = await load_questions(db, session_id)
    try:
        await _compute_feedback(db, session, questions, user_id=user_id)
    except LLMError as exc:
        await _fail(db, session, str(exc), user_id=user_id)
    except Exception as exc:  # last-resort guardrail: a crash must still resolve the row
        logger.exception("career_practice_feedback_crashed", session_id=str(session_id))
        await _fail(db, session, f"Unexpected error: {exc}", user_id=user_id)


async def _compute_feedback(
    db: AsyncSession,
    session: PracticeSession,
    questions: list[PracticeQuestion],
    *,
    user_id: uuid.UUID,
) -> None:
    answered = [q for q in questions if (q.answer_text or "").strip()]
    for question in questions:
        if question not in answered:
            # Deterministic, not an LLM judgment — no call is made for a question left blank.
            question.verdict = "missed"
            question.feedback_text = "No answer was given."

    if answered:
        llm = get_llm_provider(get_settings())
        items = [
            {
                "id": str(q.id),
                "text": q.text,
                "ref_type": q.ref_type,
                "ref_excerpt": q.ref_excerpt,
                "answer_text": q.answer_text,
            }
            for q in answered
        ]
        raw_feedback = await generate_feedback(llm, items=items)

        by_id = {str(q.id): q for q in answered}
        seen: set[str] = set()
        for raw in raw_feedback:
            question_id = str(raw.get("question_id") or "")
            matched = by_id.get(question_id)
            if matched is None or question_id in seen:
                continue
            seen.add(question_id)
            result = verify_feedback_item(
                raw, ref_excerpt=matched.ref_excerpt, answer_text=matched.answer_text or ""
            )
            if result is None:
                matched.verdict = "unclear"
                matched.feedback_text = "Feedback couldn't be verified against your answer."
            else:
                matched.verdict, matched.feedback_text = result

        for question in answered:
            if str(question.id) not in seen:
                question.verdict = "unclear"
                question.feedback_text = "Feedback couldn't be verified against your answer."

    session.status = "completed"
    session.error = None
    await db.flush()

    await log_action(
        db,
        user_id=user_id,
        action="career.practice_session.feedback_generated",
        risk_level="green",
        summary=f"Generated interview-practice feedback for {len(answered)} answered question(s).",
        evidence={"answered": len(answered), "unanswered": len(questions) - len(answered)},
        resource_type="job_posting",
        resource_id=session.job_posting_id,
    )
