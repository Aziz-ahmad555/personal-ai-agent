import uuid
from typing import Annotated

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import log_action
from app.auth.deps import get_current_user
from app.career import practice_service
from app.career.models import Application, JobPosting, PracticeQuestion, PracticeSession
from app.career.practice_schemas import (
    PracticeCounts,
    PracticeDroppedRead,
    PracticeQuestionRead,
    PracticeSessionRead,
    PracticeSessionSummary,
    StartPracticeSessionRequest,
    SubmitPracticeAnswersRequest,
)
from app.core.rate_limit import LLM_ACTION_RATE_LIMIT, limiter
from app.db import base as db_base
from app.db.base import get_db
from app.db.models import User
from app.research.llm import start_cost_guarded_task

router = APIRouter(prefix="/career", tags=["career"])

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


async def _owned_job(db: AsyncSession, job_id: uuid.UUID, user_id: uuid.UUID) -> JobPosting:
    job = (
        await db.execute(
            select(JobPosting).where(JobPosting.id == job_id, JobPosting.user_id == user_id)
        )
    ).scalar_one_or_none()
    if job is None:
        raise _NOT_FOUND
    return job


async def _owned_session(
    db: AsyncSession, session_id: uuid.UUID, user_id: uuid.UUID
) -> PracticeSession:
    session = (
        await db.execute(
            select(PracticeSession).where(
                PracticeSession.id == session_id, PracticeSession.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if session is None:
        raise _NOT_FOUND
    return session


def _tally(questions: list[PracticeQuestion]) -> PracticeCounts:
    counts = {"addressed": 0, "partially_addressed": 0, "missed": 0, "unclear": 0, "unanswered": 0}
    for question in questions:
        if not (question.answer_text or "").strip():
            counts["unanswered"] += 1
        elif question.verdict in counts:
            counts[question.verdict] += 1
        else:
            counts["missed"] += 1
    return PracticeCounts(**counts)


def _reported_status(session: PracticeSession) -> tuple[str, str | None]:
    if practice_service.is_stalled(session):
        # Report an orphaned run as failed so the UI stops polling and offers a retry.
        return "failed", practice_service.STALLED_MESSAGE
    return session.status, session.error


async def _build_detail(db: AsyncSession, session: PracticeSession) -> PracticeSessionRead:
    questions = await practice_service.load_questions(db, session.id)
    session_status, error = _reported_status(session)
    return PracticeSessionRead(
        id=session.id,
        job_posting_id=session.job_posting_id,
        application_id=session.application_id,
        status=session_status,
        error=error,
        started_at=session.started_at,
        created_at=session.created_at,
        questions=[PracticeQuestionRead.model_validate(q) for q in questions],
        dropped=[PracticeDroppedRead(**d) for d in session.dropped],
        counts=_tally(questions),
    )


async def _questions_in_background(session_id: uuid.UUID, user_id: uuid.UUID) -> None:
    # A fresh id per call, not session_id — question generation and feedback generation
    # are two separate tasks against the same session, and either could in principle be
    # retried for it, so session_id alone wouldn't stay unique per invocation.
    structlog.contextvars.bind_contextvars(task_id=str(uuid.uuid4()))
    start_cost_guarded_task()  # enables SpendGuardedProvider's enforcement for this task
    async with db_base.async_session_factory() as db:
        await practice_service.run_question_generation(db, session_id, user_id=user_id)
        await db.commit()


async def _feedback_in_background(session_id: uuid.UUID, user_id: uuid.UUID) -> None:
    structlog.contextvars.bind_contextvars(task_id=str(uuid.uuid4()))
    start_cost_guarded_task()  # enables SpendGuardedProvider's enforcement for this task
    async with db_base.async_session_factory() as db:
        await practice_service.run_feedback_generation(db, session_id, user_id=user_id)
        await db.commit()


@router.post("/jobs/{job_id}/practice-sessions", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit(LLM_ACTION_RATE_LIMIT)
async def start_practice_session(
    request: Request,
    job_id: uuid.UUID,
    body: StartPracticeSessionRequest,
    background_tasks: BackgroundTasks,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, str]:
    job = await _owned_job(db, job_id, user.id)
    if not await practice_service.has_completed_match(db, job.id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Score this job's match first — practice reuses its verified requirements.",
        )
    if body.application_id is not None:
        application = await db.get(Application, body.application_id)
        if (
            application is None
            or application.user_id != user.id
            or application.job_posting_id != job.id
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="That application isn't linked to this job.",
            )

    # The "is there already an active session" check and the session creation must happen as
    # one unit — see app.career.practice_service.job_lock for why (a real, red-team-found race
    # otherwise).
    async with practice_service.job_lock(job.id):
        if await practice_service.get_active_session(db, job.id) is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A practice session for this job is already in progress.",
            )
        session = await practice_service.start_session(
            db, job, user.id, application_id=body.application_id
        )
        await db.commit()
    background_tasks.add_task(_questions_in_background, session.id, user.id)
    return {"status": "questions_started"}


@router.get("/jobs/{job_id}/practice-sessions", response_model=list[PracticeSessionSummary])
async def list_job_practice_sessions(
    job_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[PracticeSessionSummary]:
    job = await _owned_job(db, job_id, user.id)
    sessions = await practice_service.list_sessions(db, job.id)
    summaries = []
    for session in sessions:
        questions = await practice_service.load_questions(db, session.id)
        session_status, error = _reported_status(session)
        summaries.append(
            PracticeSessionSummary(
                id=session.id,
                status=session_status,
                error=error,
                started_at=session.started_at,
                created_at=session.created_at,
                question_count=len(questions),
                counts=_tally(questions),
            )
        )
    return summaries


@router.get("/practice-sessions/{session_id}", response_model=PracticeSessionRead)
async def get_practice_session(
    session_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PracticeSessionRead:
    session = await _owned_session(db, session_id, user.id)
    return await _build_detail(db, session)


@router.patch("/practice-sessions/{session_id}/answers", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit(LLM_ACTION_RATE_LIMIT)
async def submit_practice_answers(
    request: Request,
    session_id: uuid.UUID,
    body: SubmitPracticeAnswersRequest,
    background_tasks: BackgroundTasks,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, str]:
    session = await _owned_session(db, session_id, user.id)
    questions = await practice_service.load_questions(db, session.id)
    # Also allowed as a retry when a previous feedback run failed (e.g. an LLM outage) —
    # the user's answers are already saved, so they shouldn't have to retype them.
    can_submit = session.status == "ready_for_answers" or (session.status == "failed" and questions)
    if not can_submit:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This session isn't ready for answers."
        )
    try:
        await practice_service.submit_answers(db, session, body.answers, user_id=user.id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    await db.commit()
    background_tasks.add_task(_feedback_in_background, session.id, user.id)
    return {"status": "feedback_started"}


@router.delete("/practice-sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_practice_session(
    session_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    session = await _owned_session(db, session_id, user.id)
    await log_action(
        db,
        user_id=user.id,
        action="career.practice_session.deleted",
        risk_level="green",
        summary="Deleted an interview-practice session.",
        resource_type="job_posting",
        resource_id=session.job_posting_id,
    )
    await db.delete(session)
    await db.commit()
