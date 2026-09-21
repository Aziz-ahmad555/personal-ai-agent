import re
import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import log_action
from app.auth.deps import get_current_user
from app.career import cover_service
from app.career.cover_schemas import (
    CoverCounts,
    CoverDecision,
    CoverDroppedRead,
    CoverEdit,
    CoverExport,
    CoverLetterRead,
    CoverParagraphRead,
)
from app.career.models import CoverLetter, CoverLetterParagraph, JobPosting
from app.career.resume_schemas import ResumeGapRead
from app.career.resume_service import load_base_resume
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


async def _owned_letter(
    db: AsyncSession, letter_id: uuid.UUID, user_id: uuid.UUID
) -> CoverLetter:
    letter = (
        await db.execute(
            select(CoverLetter).where(CoverLetter.id == letter_id, CoverLetter.user_id == user_id)
        )
    ).scalar_one_or_none()
    if letter is None:
        raise _NOT_FOUND
    return letter


async def _owned_paragraph(
    db: AsyncSession, letter: CoverLetter, paragraph_id: uuid.UUID
) -> CoverLetterParagraph:
    paragraph = (
        await db.execute(
            select(CoverLetterParagraph).where(
                CoverLetterParagraph.id == paragraph_id,
                CoverLetterParagraph.letter_id == letter.id,
            )
        )
    ).scalar_one_or_none()
    if paragraph is None:
        raise _NOT_FOUND
    return paragraph


def _paragraph_read(paragraph: CoverLetterParagraph) -> CoverParagraphRead:
    read = CoverParagraphRead.model_validate(paragraph)
    return read.model_copy(update={"is_edited": bool(paragraph.edited_text)})


async def _build_detail(db: AsyncSession, letter: CoverLetter) -> CoverLetterRead:
    paragraphs = await cover_service.load_paragraphs(db, letter.id)
    counts = CoverCounts(
        accepted=sum(p.decision == "accepted" for p in paragraphs),
        rejected=sum(p.decision == "rejected" for p in paragraphs),
        pending=sum(p.decision == "pending" for p in paragraphs),
    )

    letter_status = letter.status
    error = letter.error
    if cover_service.is_stalled(letter):
        # Report an orphaned run as failed so the UI stops polling and offers a retry.
        letter_status, error = "failed", cover_service.STALLED_MESSAGE

    is_stale = False
    if letter.status == "completed" and letter.profile_stamp:
        current = await load_base_resume(db, letter.user_id)
        is_stale = current.stamp() != letter.profile_stamp

    return CoverLetterRead(
        id=letter.id,
        job_posting_id=letter.job_posting_id,
        status=letter_status,
        error=error,
        is_stale=is_stale,
        started_at=letter.started_at,
        paragraphs=[_paragraph_read(p) for p in paragraphs],
        gaps=[ResumeGapRead(**g) for g in letter.gaps],
        dropped=[CoverDroppedRead(**d) for d in letter.dropped],
        counts=counts,
        preview_text=cover_service.render_current(letter, paragraphs),
    )


async def _draft_in_background(job_id: uuid.UUID, user_id: uuid.UUID) -> None:
    async with db_base.async_session_factory() as db:
        await cover_service.run_letter(db, job_id, user_id=user_id)
        await db.commit()


@router.post("/jobs/{job_id}/cover-letter", status_code=status.HTTP_202_ACCEPTED)
async def draft_cover_letter(
    job_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, str]:
    job = await _owned_job(db, job_id, user.id)
    # Create/reset the row now so the client's next fetch sees "running", not a gap.
    await cover_service.start_letter(db, job, user.id)
    await db.commit()
    background_tasks.add_task(_draft_in_background, job_id, user.id)
    return {"status": "drafting_started"}


@router.get("/jobs/{job_id}/cover-letter", response_model=CoverLetterRead)
async def get_job_cover_letter(
    job_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CoverLetterRead:
    job = await _owned_job(db, job_id, user.id)
    letter = (
        await db.execute(select(CoverLetter).where(CoverLetter.job_posting_id == job.id))
    ).scalar_one_or_none()
    if letter is None:
        raise _NOT_FOUND
    return await _build_detail(db, letter)


@router.post(
    "/cover-letters/{letter_id}/paragraphs/{paragraph_id}/decision",
    response_model=CoverLetterRead,
)
async def decide_paragraph(
    letter_id: uuid.UUID,
    paragraph_id: uuid.UUID,
    body: CoverDecision,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CoverLetterRead:
    letter = await _owned_letter(db, letter_id, user.id)
    paragraph = await _owned_paragraph(db, letter, paragraph_id)
    await cover_service.decide_paragraph(
        db, letter, paragraph, decision=body.decision, user_id=user.id
    )
    await db.commit()
    return await _build_detail(db, letter)


@router.patch(
    "/cover-letters/{letter_id}/paragraphs/{paragraph_id}", response_model=CoverLetterRead
)
async def edit_paragraph(
    letter_id: uuid.UUID,
    paragraph_id: uuid.UUID,
    body: CoverEdit,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CoverLetterRead:
    letter = await _owned_letter(db, letter_id, user.id)
    paragraph = await _owned_paragraph(db, letter, paragraph_id)
    await cover_service.edit_paragraph(db, letter, paragraph, text=body.text, user_id=user.id)
    await db.commit()
    return await _build_detail(db, letter)


def _filename(job: JobPosting | None) -> str:
    raw = f"{job.company_name or ''}-{job.title or ''}" if job else ""
    slug = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")
    return f"cover-letter-{slug}.txt" if slug else "cover-letter.txt"


@router.get("/cover-letters/{letter_id}/export", response_model=CoverExport)
async def export_cover_letter(
    letter_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CoverExport:
    letter = await _owned_letter(db, letter_id, user.id)
    if letter.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This draft isn't ready to export."
        )
    paragraphs = await cover_service.load_paragraphs(db, letter.id)
    accepted = [p for p in paragraphs if p.decision == "accepted"]
    if not accepted:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Accept at least one paragraph before exporting.",
        )
    job = await db.get(JobPosting, letter.job_posting_id)
    edited = sum(1 for p in accepted if p.edited_text)
    await log_action(
        db,
        user_id=user.id,
        action="career.cover_letter.exported",
        risk_level="green",
        summary="Exported a cover letter as text.",
        resource_type="cover_letter",
        resource_id=letter.id,
        evidence={"accepted": len(accepted), "edited_not_fact_checked": edited},
    )
    await db.commit()
    return CoverExport(
        filename=_filename(job),
        text=cover_service.render_current(letter, paragraphs),
        accepted=len(accepted),
        pending=sum(p.decision == "pending" for p in paragraphs),
        rejected=sum(p.decision == "rejected" for p in paragraphs),
        edited=edited,
    )


@router.delete("/cover-letters/{letter_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_cover_letter(
    letter_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    letter = await _owned_letter(db, letter_id, user.id)
    await log_action(
        db,
        user_id=user.id,
        action="career.cover_letter.deleted",
        risk_level="green",
        summary="Deleted a cover letter draft.",
        resource_type="cover_letter",
        resource_id=letter.id,
    )
    await db.delete(letter)
    await db.commit()
