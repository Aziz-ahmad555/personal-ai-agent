import re
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import log_action
from app.auth.deps import get_current_user
from app.career import resume_service
from app.career.ats_check import check_keywords, check_structure, summarize
from app.career.ats_render import render_ats_plain
from app.career.ats_schemas import (
    AtsCheckItem,
    AtsCheckRead,
    AtsKeywordRead,
    AtsKeywordStats,
    AtsSafeExport,
    AtsSummary,
    ResumeSource,
)
from app.career.models import JobMatch, JobPosting, TailoredResume
from app.career.resume_base import ResumeBase, apply_accepted, render_markdown
from app.db.base import get_db
from app.db.models import User

router = APIRouter(prefix="/career/jobs", tags=["career"])

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


async def _resume_for_job(
    db: AsyncSession, job: JobPosting, user_id: uuid.UUID
) -> tuple[ResumeBase, ResumeSource, int]:
    """The resume as it stands for this job: the tailored draft with only its accepted changes
    applied if the user has accepted any, otherwise the resume built from the current profile."""
    draft = (
        await db.execute(select(TailoredResume).where(TailoredResume.job_posting_id == job.id))
    ).scalar_one_or_none()
    if draft is not None and draft.status == "completed" and draft.base:
        changes = await resume_service.load_changes(db, draft.id)
        accepted = sum(1 for c in changes if c.decision == "accepted")
        if accepted:
            return apply_accepted(ResumeBase.from_json(draft.base), changes), "tailored", accepted
    return await resume_service.load_base_resume(db, user_id), "profile", 0


async def _requirements(db: AsyncSession, job: JobPosting) -> list[dict[str, str]]:
    """The posting's quote-verified skill requirements, from the match. Requiring a completed match
    keeps this check instant and free of any LLM call."""
    match = (
        await db.execute(select(JobMatch).where(JobMatch.job_posting_id == job.id))
    ).scalar_one_or_none()
    if match is None or match.status != "completed" or not match.requirements:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Run the match for this job first — the ATS check uses the requirements it "
            "read from the posting.",
        )
    required = match.requirements.get("required_skills") or []
    preferred = match.requirements.get("preferred_skills") or []
    return [
        *({"name": r["name"], "kind": "required", "quote": r["quote"]} for r in required),
        *({"name": p["name"], "kind": "preferred", "quote": p["quote"]} for p in preferred),
    ]


@router.post("/{job_id}/ats-check", response_model=AtsCheckRead)
async def run_ats_check(
    job_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AtsCheckRead:
    job = await _owned_job(db, job_id, user.id)
    requirements = await _requirements(db, job)
    base, source, accepted = await _resume_for_job(db, job, user.id)

    text = render_markdown(base)
    keywords, stats = check_keywords(text, requirements, base)
    checks = check_structure(text)
    summary = summarize(checks)

    await log_action(
        db,
        user_id=user.id,
        action="career.ats.checked",
        risk_level="green",
        summary="Ran an ATS compatibility check on a resume.",
        evidence={
            "resume_source": source,
            "keyword_coverage_percent": stats.coverage_percent,
            "passed": summary["pass"],
            "warn": summary["warn"],
            "fail": summary["fail"],
        },
        resource_type="job_posting",
        resource_id=job.id,
    )
    await db.commit()

    return AtsCheckRead(
        resume_source=source,
        accepted_changes=accepted,
        keyword_stats=AtsKeywordStats(**stats.__dict__),
        keywords=[AtsKeywordRead(**k.__dict__) for k in keywords],
        checks=[AtsCheckItem(**c.__dict__) for c in checks],
        summary=AtsSummary(passed=summary["pass"], warn=summary["warn"], fail=summary["fail"]),
    )


def _filename(job: JobPosting) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", f"{job.company_name or ''}-{job.title or ''}".lower())
    slug = slug.strip("-")
    return f"resume-{slug}-ats-safe.txt" if slug else "resume-ats-safe.txt"


@router.get("/{job_id}/ats-safe", response_model=AtsSafeExport)
async def export_ats_safe(
    job_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AtsSafeExport:
    job = await _owned_job(db, job_id, user.id)
    base, source, accepted = await _resume_for_job(db, job, user.id)
    await log_action(
        db,
        user_id=user.id,
        action="career.ats.safe_exported",
        risk_level="green",
        summary="Exported an ATS-safe plain-text resume.",
        evidence={"resume_source": source, "accepted_changes": accepted},
        resource_type="job_posting",
        resource_id=job.id,
    )
    await db.commit()
    return AtsSafeExport(
        filename=_filename(job),
        text=render_ats_plain(base),
        resume_source=source,
        accepted_changes=accepted,
    )
