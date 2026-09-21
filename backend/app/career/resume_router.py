import re
import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import log_action
from app.auth.deps import get_current_user
from app.career import resume_service
from app.career.models import JobPosting, ResumeChange, TailoredResume
from app.career.resume_schemas import (
    ResumeChangeRead,
    ResumeCounts,
    ResumeDecision,
    ResumeDroppedRead,
    ResumeExport,
    ResumeGapRead,
    TailoredResumeRead,
)
from app.db import base as db_base
from app.db.base import get_db
from app.db.models import User

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


async def _owned_resume(
    db: AsyncSession, resume_id: uuid.UUID, user_id: uuid.UUID
) -> TailoredResume:
    resume = (
        await db.execute(
            select(TailoredResume).where(
                TailoredResume.id == resume_id, TailoredResume.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if resume is None:
        raise _NOT_FOUND
    return resume


async def _build_detail(db: AsyncSession, resume: TailoredResume) -> TailoredResumeRead:
    changes = await resume_service.load_changes(db, resume.id)
    counts = ResumeCounts(
        accepted=sum(c.decision == "accepted" for c in changes),
        rejected=sum(c.decision == "rejected" for c in changes),
        pending=sum(c.decision == "pending" for c in changes),
    )

    resume_status = resume.status
    error = resume.error
    if resume_service.is_stalled(resume):
        # Report an orphaned run as failed so the UI stops polling and offers a retry.
        resume_status, error = "failed", resume_service.STALLED_MESSAGE

    is_stale = False
    if resume.status == "completed" and resume.profile_stamp:
        current = await resume_service.load_base_resume(db, resume.user_id)
        is_stale = current.stamp() != resume.profile_stamp

    return TailoredResumeRead(
        id=resume.id,
        job_posting_id=resume.job_posting_id,
        status=resume_status,
        error=error,
        is_stale=is_stale,
        started_at=resume.started_at,
        changes=[ResumeChangeRead.model_validate(c) for c in changes],
        gaps=[ResumeGapRead(**g) for g in resume.gaps],
        dropped=[ResumeDroppedRead(**d) for d in resume.dropped],
        counts=counts,
        preview_markdown=resume_service.render_current(resume, changes),
    )


async def _tailor_in_background(job_id: uuid.UUID, user_id: uuid.UUID) -> None:
    async with db_base.async_session_factory() as db:
        await resume_service.run_tailor(db, job_id, user_id=user_id)
        await db.commit()


@router.post("/jobs/{job_id}/tailor", status_code=status.HTTP_202_ACCEPTED)
async def tailor_resume(
    job_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, str]:
    job = await _owned_job(db, job_id, user.id)
    # Create/reset the row now so the client's next fetch sees "running", not a gap.
    await resume_service.start_tailor(db, job, user.id)
    await db.commit()
    background_tasks.add_task(_tailor_in_background, job_id, user.id)
    return {"status": "tailoring_started"}


@router.get("/jobs/{job_id}/resume", response_model=TailoredResumeRead)
async def get_job_resume(
    job_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TailoredResumeRead:
    job = await _owned_job(db, job_id, user.id)
    resume = (
        await db.execute(select(TailoredResume).where(TailoredResume.job_posting_id == job.id))
    ).scalar_one_or_none()
    if resume is None:
        raise _NOT_FOUND
    return await _build_detail(db, resume)


@router.post(
    "/resumes/{resume_id}/changes/{change_id}/decision", response_model=TailoredResumeRead
)
async def decide(
    resume_id: uuid.UUID,
    change_id: uuid.UUID,
    body: ResumeDecision,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TailoredResumeRead:
    resume = await _owned_resume(db, resume_id, user.id)
    change = (
        await db.execute(
            select(ResumeChange).where(
                ResumeChange.id == change_id, ResumeChange.resume_id == resume.id
            )
        )
    ).scalar_one_or_none()
    if change is None:
        raise _NOT_FOUND
    await resume_service.decide_change(db, resume, change, decision=body.decision, user_id=user.id)
    await db.commit()
    return await _build_detail(db, resume)


def _filename(job: JobPosting | None) -> str:
    raw = f"{job.company_name or ''}-{job.title or ''}" if job else ""
    slug = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")
    return f"resume-{slug}.md" if slug else "resume.md"


@router.get("/resumes/{resume_id}/export", response_model=ResumeExport)
async def export_resume(
    resume_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ResumeExport:
    resume = await _owned_resume(db, resume_id, user.id)
    if resume.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This draft isn't ready to export."
        )
    changes = await resume_service.load_changes(db, resume.id)
    job = await db.get(JobPosting, resume.job_posting_id)
    accepted = sum(c.decision == "accepted" for c in changes)
    await log_action(
        db,
        user_id=user.id,
        action="career.resume.exported",
        risk_level="green",
        summary="Exported a tailored resume as Markdown.",
        resource_type="tailored_resume",
        resource_id=resume.id,
        evidence={"accepted": accepted},
    )
    await db.commit()
    return ResumeExport(
        filename=_filename(job),
        markdown=resume_service.render_current(resume, changes),
        accepted=accepted,
        pending=sum(c.decision == "pending" for c in changes),
        rejected=sum(c.decision == "rejected" for c in changes),
    )


@router.delete("/resumes/{resume_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_resume(
    resume_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    resume = await _owned_resume(db, resume_id, user.id)
    await log_action(
        db,
        user_id=user.id,
        action="career.resume.deleted",
        risk_level="green",
        summary="Deleted a tailored resume draft.",
        resource_type="tailored_resume",
        resource_id=resume.id,
    )
    await db.delete(resume)
    await db.commit()
