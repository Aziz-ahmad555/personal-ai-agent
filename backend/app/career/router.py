import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.career.discovery import (
    DiscoveryError,
    capture_job_from_text,
    capture_job_from_url,
    poll_company_feed,
)
from app.career.models import EmployerVerification, JobBoardFeed, JobFraudAssessment, JobPosting
from app.career.schemas import (
    EmployerVerificationRead,
    JobBoardFeedCreate,
    JobBoardFeedRead,
    JobFraudAssessmentRead,
    JobPostingCreateFromText,
    JobPostingCreateFromUrl,
    JobPostingRead,
)
from app.career.verification import employer_key_for, verify_and_assess_job
from app.db import base as db_base
from app.db.base import get_db
from app.db.models import User
from app.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/career/jobs", tags=["career"])

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


async def _build_job_read(db: AsyncSession, job: JobPosting) -> JobPostingRead:
    """Nested employer_verification/fraud_assessment aren't SQLAlchemy relationships on
    JobPosting (EmployerVerification is keyed per-employer, shared across postings, not a
    1:1 FK) — fetched separately and attached, the same manual-assembly approach
    app.research.router uses for ResearchQueryDetail rather than a magic ORM walk."""
    fraud = (
        await db.execute(
            select(JobFraudAssessment).where(JobFraudAssessment.job_posting_id == job.id)
        )
    ).scalar_one_or_none()

    employer_verification = None
    key = employer_key_for(company_name=job.company_name, company_domain=job.company_domain)
    if key:
        employer_verification = (
            await db.execute(
                select(EmployerVerification).where(EmployerVerification.employer_key == key)
            )
        ).scalar_one_or_none()

    data = JobPostingRead.model_validate(job)
    return data.model_copy(
        update={
            "fraud_assessment": (
                JobFraudAssessmentRead.model_validate(fraud) if fraud is not None else None
            ),
            "employer_verification": (
                EmployerVerificationRead.model_validate(employer_verification)
                if employer_verification is not None
                else None
            ),
        }
    )


@router.post("/from-url", response_model=JobPostingRead, status_code=status.HTTP_201_CREATED)
async def create_from_url(
    body: JobPostingCreateFromUrl,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> JobPostingRead:
    try:
        posting = await capture_job_from_url(db, user_id=user.id, url=str(body.url))
    except DiscoveryError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    await db.commit()
    await db.refresh(posting)
    return await _build_job_read(db, posting)


@router.post("/paste", response_model=JobPostingRead, status_code=status.HTTP_201_CREATED)
async def create_from_paste(
    body: JobPostingCreateFromText,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> JobPostingRead:
    try:
        posting = await capture_job_from_text(db, user_id=user.id, raw_text=body.raw_text)
    except DiscoveryError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    await db.commit()
    await db.refresh(posting)
    return await _build_job_read(db, posting)


@router.get("", response_model=list[JobPostingRead])
async def list_jobs(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[JobPostingRead]:
    result = await db.execute(
        select(JobPosting)
        .where(JobPosting.user_id == user.id)
        .order_by(JobPosting.discovered_at.desc())
    )
    jobs = list(result.scalars().all())
    return [await _build_job_read(db, job) for job in jobs]


async def _get_owned_job(db: AsyncSession, job_id: uuid.UUID, user_id: uuid.UUID) -> JobPosting:
    result = await db.execute(
        select(JobPosting).where(JobPosting.id == job_id, JobPosting.user_id == user_id)
    )
    job = result.scalar_one_or_none()
    if job is None:
        raise _NOT_FOUND
    return job


# The /feeds routes are registered before /{job_id}: FastAPI matches path operations in
# registration order, so a static "/feeds" segment must come first or it gets swallowed by
# "/{job_id}" (with job_id="feeds", which then 422s trying to parse "feeds" as a UUID).


@router.post("/feeds", response_model=JobBoardFeedRead, status_code=status.HTTP_201_CREATED)
async def create_feed(
    body: JobBoardFeedCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> JobBoardFeed:
    feed = JobBoardFeed(
        user_id=user.id, board=body.board, company_slug=body.company_slug, keyword=body.keyword
    )
    db.add(feed)
    await db.commit()
    await db.refresh(feed)
    return feed


@router.get("/feeds", response_model=list[JobBoardFeedRead])
async def list_feeds(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[JobBoardFeed]:
    result = await db.execute(select(JobBoardFeed).where(JobBoardFeed.user_id == user.id))
    return list(result.scalars().all())


async def _get_owned_feed(db: AsyncSession, feed_id: uuid.UUID, user_id: uuid.UUID) -> JobBoardFeed:
    result = await db.execute(
        select(JobBoardFeed).where(JobBoardFeed.id == feed_id, JobBoardFeed.user_id == user_id)
    )
    feed = result.scalar_one_or_none()
    if feed is None:
        raise _NOT_FOUND
    return feed


@router.delete("/feeds/{feed_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_feed(
    feed_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    feed = await _get_owned_feed(db, feed_id, user.id)
    await db.delete(feed)
    await db.commit()


async def _poll_feed_in_background(feed_id: uuid.UUID) -> None:
    async with db_base.async_session_factory() as db:
        feed = await db.get(JobBoardFeed, feed_id)
        if feed is None:
            logger.warning("career_feed_not_found", feed_id=str(feed_id))
            return
        try:
            await poll_company_feed(db, feed)
        except DiscoveryError:
            pass  # already recorded on the feed and in the audit log
        await db.commit()


@router.post("/feeds/{feed_id}/poll", status_code=status.HTTP_202_ACCEPTED)
async def poll_feed(
    feed_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, str]:
    await _get_owned_feed(db, feed_id, user.id)  # ownership check
    background_tasks.add_task(_poll_feed_in_background, feed_id)
    return {"status": "polling_started"}


@router.get("/{job_id}", response_model=JobPostingRead)
async def get_job(
    job_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> JobPostingRead:
    job = await _get_owned_job(db, job_id, user.id)
    return await _build_job_read(db, job)


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_job(
    job_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    job = await _get_owned_job(db, job_id, user.id)
    await db.delete(job)
    await db.commit()


async def _verify_job_in_background(job_id: uuid.UUID, user_id: uuid.UUID) -> None:
    async with db_base.async_session_factory() as db:
        await verify_and_assess_job(db, job_id, user_id=user_id)
        await db.commit()


@router.post("/{job_id}/verify", status_code=status.HTTP_202_ACCEPTED)
async def verify_job(
    job_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, str]:
    await _get_owned_job(db, job_id, user.id)  # ownership check
    background_tasks.add_task(_verify_job_in_background, job_id, user.id)
    return {"status": "verification_started"}
