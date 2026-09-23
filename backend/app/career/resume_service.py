"""Resume tailoring orchestration. Green risk: it reads the user's own profile and a posting and
writes a local draft — nothing leaves the system, and nothing takes effect until the user
accepts changes one by one. Logged to the audit trail.

Flow: assemble the base resume from the profile -> get the posting's verified requirements ->
one LLM call proposing rewordings -> plain-code verification of every proposal (fabricated
claims are dropped, and counted) -> plain-code skill reordering and gap detection -> persist.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.audit.service import log_action
from app.career.matching import normalize_skill
from app.career.models import JobMatch, JobPosting, ResumeChange, TailoredResume
from app.career.requirements import extract_requirements
from app.career.resume_base import (
    EducationItem,
    ExperienceItem,
    ResumeBase,
    SkillItem,
    apply_accepted,
    render_markdown,
)
from app.career.resume_llm import RewriteProposal, TailorItem, propose_rewrites
from app.career.resume_verify import find_gaps, reorder_skills, verify_rewrite, words_in
from app.config import get_settings
from app.db.models import User
from app.logging import get_logger
from app.profile.models import Profile, Skill
from app.research.llm import LLMError, get_llm_provider

logger = get_logger(__name__)

# Same reasoning as MATCH_TIMEOUT: a healthy run can take minutes under provider overload, but
# a background task dies with the server, so past this the run is presumed dead.
TAILOR_TIMEOUT = timedelta(minutes=10)
STALLED_MESSAGE = (
    "This run didn't finish — the server was probably restarted while it was working. Try again."
)


class TailorError(RuntimeError):
    """The resume couldn't be tailored at all; the message is shown to the user as-is."""


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def is_stalled(resume: TailoredResume, *, now: datetime | None = None) -> bool:
    if resume.status != "running":
        return False
    return (now or datetime.now(UTC)) - _as_utc(resume.started_at) > TAILOR_TIMEOUT


async def load_base_resume(db: AsyncSession, user_id: uuid.UUID) -> ResumeBase:
    user = await db.get(User, user_id)
    profile = (
        await db.execute(
            select(Profile)
            .where(Profile.user_id == user_id)
            .options(
                selectinload(Profile.experiences),
                selectinload(Profile.educations),
                selectinload(Profile.skills).selectinload(Skill.versions),
            )
        )
    ).scalar_one_or_none()
    base = ResumeBase(
        name=user.full_name if user else None,
        headline=profile.headline if profile else None,
        location=profile.location if profile else None,
        summary=profile.summary if profile else None,
    )
    if profile is None:
        return base

    linked: dict[str, list[str]] = {}
    # Stable order, so a draft (and its diff) doesn't shuffle between runs.
    for skill in sorted(profile.skills, key=lambda s: (_as_utc(s.created_at), s.name)):
        if not skill.versions:
            base.unevidenced_skills.append(skill.name)
            continue
        latest = max(skill.versions, key=lambda v: _as_utc(v.asserted_at))
        base.skills.append(
            SkillItem(
                name=skill.name,
                level=latest.level,
                category=skill.category,
                evidence=latest.evidence,
            )
        )
        for version in skill.versions:
            if version.work_experience_id is not None:
                names = linked.setdefault(str(version.work_experience_id), [])
                if skill.name not in names:
                    names.append(skill.name)

    base.experiences = [
        ExperienceItem(
            id=str(e.id),
            company=e.company,
            title=e.title,
            location=e.location,
            start=e.start_date.isoformat(),
            end=e.end_date.isoformat() if e.end_date else None,
            description=e.description,
            linked_skills=linked.get(str(e.id), []),
        )
        for e in sorted(profile.experiences, key=lambda x: x.start_date, reverse=True)
    ]
    base.educations = [
        EducationItem(
            id=str(e.id),
            institution=e.institution,
            degree=e.degree,
            field=e.field,
            start=e.start_date.isoformat() if e.start_date else None,
            end=e.end_date.isoformat() if e.end_date else None,
        )
        for e in profile.educations
    ]
    return base


async def start_tailor(db: AsyncSession, job: JobPosting, user_id: uuid.UUID) -> TailoredResume:
    """Creates (or resets) the row, so the UI has something to poll. Regenerating discards the
    previous draft and the decisions made on it — the UI confirms before calling this."""
    resume = (
        await db.execute(select(TailoredResume).where(TailoredResume.job_posting_id == job.id))
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if resume is None:
        resume = TailoredResume(
            user_id=user_id, job_posting_id=job.id, status="running", started_at=now
        )
        db.add(resume)
        try:
            await db.flush()
        except IntegrityError:
            # Found by a red-team pass (same fix as app.career.match_service.start_match): a
            # concurrent request can win this exact race. Recover by resetting the row that
            # already exists instead of surfacing a raw database error.
            await db.rollback()
            resume = (
                await db.execute(
                    select(TailoredResume).where(TailoredResume.job_posting_id == job.id)
                )
            ).scalar_one()
            await _reset(db, resume, now)
        return resume
    await _reset(db, resume, now)
    return resume


async def _reset(db: AsyncSession, resume: TailoredResume, now: datetime) -> None:
    await db.execute(delete(ResumeChange).where(ResumeChange.resume_id == resume.id))
    resume.status = "running"
    resume.error = None
    resume.started_at = now
    resume.base = None
    resume.requirements = []
    resume.gaps = []
    resume.dropped = []
    resume.profile_stamp = None
    await db.flush()


async def run_tailor(db: AsyncSession, job_posting_id: uuid.UUID, *, user_id: uuid.UUID) -> None:
    job = await db.get(JobPosting, job_posting_id)
    if job is None:
        logger.warning("career_job_not_found_for_tailor", job_posting_id=str(job_posting_id))
        return
    resume = await start_tailor(db, job, user_id)
    try:
        await _compute(db, job, resume, user_id=user_id)
    except (TailorError, LLMError) as exc:
        await _fail(db, job, resume, str(exc), user_id=user_id)
    except Exception as exc:  # last-resort guardrail: a crash must still resolve the row
        logger.exception("career_tailor_crashed", job_posting_id=str(job_posting_id))
        await _fail(db, job, resume, f"Unexpected error: {exc}", user_id=user_id)


async def _fail(
    db: AsyncSession, job: JobPosting, resume: TailoredResume, message: str, *, user_id: uuid.UUID
) -> None:
    resume.status = "failed"
    resume.error = message
    await db.flush()
    await log_action(
        db,
        user_id=user_id,
        action="career.resume.tailor_failed",
        risk_level="green",
        summary="Could not tailor a resume for a job posting.",
        resource_type="job_posting",
        resource_id=job.id,
        error=message,
    )


async def requirements_for(db: AsyncSession, job: JobPosting, llm: Any) -> list[dict[str, Any]]:
    """The posting's verified skill requirements: reuse the match's (already quote-checked) if
    there is one, otherwise read them fresh with the same quote-checked extractor."""
    match = (
        await db.execute(select(JobMatch).where(JobMatch.job_posting_id == job.id))
    ).scalar_one_or_none()
    required: list[dict[str, str]] = []
    preferred: list[dict[str, str]] = []
    if match is not None and match.status == "completed" and match.requirements:
        required = list(match.requirements.get("required_skills") or [])
        preferred = list(match.requirements.get("preferred_skills") or [])
    else:
        description = (job.description_text or "").strip()
        extracted = await extract_requirements(llm, description=description)
        required = [{"name": s.name, "quote": s.quote} for s in extracted.required_skills]
        preferred = [{"name": s.name, "quote": s.quote} for s in extracted.preferred_skills]
    return [
        *({"name": r["name"], "kind": "required", "quote": r["quote"]} for r in required),
        *({"name": p["name"], "kind": "preferred", "quote": p["quote"]} for p in preferred),
    ]


def _experience_label(exp: ExperienceItem) -> str:
    return f"{exp.title} — {exp.company}"


async def _compute(
    db: AsyncSession, job: JobPosting, resume: TailoredResume, *, user_id: uuid.UUID
) -> None:
    if not (job.description_text or "").strip():
        raise TailorError(
            "This posting has no description text to tailor toward — paste the full posting first."
        )
    base = await load_base_resume(db, user_id)
    if not base.has_tailorable_content:
        raise TailorError(
            "Your profile has no summary or work-history descriptions yet, so there's nothing "
            "to tailor. Add some on the Profile page first."
        )

    llm = get_llm_provider(get_settings())
    requirements = await requirements_for(db, job, llm)
    if not requirements:
        raise TailorError(
            "No skill requirements could be read from this posting, so there's nothing to "
            "tailor toward. Paste the full posting."
        )

    required_names = [r["name"] for r in requirements if r["kind"] == "required"]
    preferred_names = [r["name"] for r in requirements if r["kind"] == "preferred"]
    by_norm = {normalize_skill(r["name"]): r for r in requirements}

    items: list[TailorItem] = []
    if (base.summary or "").strip():
        items.append(TailorItem("summary", "Professional summary", base.summary or ""))
    for exp in base.experiences:
        if (exp.description or "").strip():
            items.append(TailorItem(f"exp:{exp.id}", _experience_label(exp), exp.description or ""))
    items_by_id = {item.source_id: item for item in items}
    experiences_by_id = {f"exp:{e.id}": e for e in base.experiences}

    proposals: list[RewriteProposal] = await propose_rewrites(
        llm,
        job_title=job.title,
        company=job.company_name,
        requirements=requirements,
        items=items,
    )

    watch_terms = list(
        dict.fromkeys(
            [r["name"] for r in requirements]
            + [s.name for s in base.skills]
            + base.unevidenced_skills
        )
    )
    all_words = words_in(base.all_text())
    evidenced_norms = {normalize_skill(s.name) for s in base.skills}

    changes: list[ResumeChange] = []
    dropped: list[dict[str, str]] = []
    seen: set[str] = set()
    position = 0

    def reject(label: str, reason: str) -> None:
        dropped.append({"source": label, "reason": reason})

    for proposal in proposals:
        item = items_by_id.get(proposal.source_id)
        if item is None:
            reject(proposal.source_id, "it referred to something that isn't on your resume")
            continue
        if proposal.source_id in seen:
            continue
        seen.add(proposal.source_id)
        if proposal.new_text.strip() == item.text.strip():
            continue  # nothing changed: not a suggestion, and not a violation either

        addressed = [
            by_norm[normalize_skill(a)] for a in proposal.addresses if normalize_skill(a) in by_norm
        ]
        addresses = [{"requirement": r["name"], "quote": r["quote"]} for r in addressed]
        if not addresses:
            reject(item.label, "it didn't address any requirement from the posting")
            continue

        if proposal.source_id == "summary":
            allowed_words = all_words
            allowed_norms = evidenced_norms
        else:
            exp = experiences_by_id[proposal.source_id]
            allowed_words = words_in(f"{exp.company} {exp.title} {exp.location or ''}") | words_in(
                " ".join(exp.linked_skills)
            )
            allowed_norms = {normalize_skill(n) for n in exp.linked_skills}

        reason = verify_rewrite(
            source_text=item.text,
            new_text=proposal.new_text,
            allowed_words=allowed_words,
            allowed_skill_norms=allowed_norms,
            watch_terms=watch_terms,
        )
        if reason:
            reject(item.label, reason)
            continue

        changes.append(
            ResumeChange(
                resume_id=resume.id,
                change_type="rewrite",
                target_id=proposal.source_id,
                target_label=item.label,
                before_text=item.text,
                after_text=proposal.new_text,
                rationale=proposal.rationale or "Reworded to speak to this posting.",
                addresses=addresses,
                position=position,
            )
        )
        position += 1

    new_order = reorder_skills(base.skills, required_names, preferred_names)
    if new_order is not None:
        skill_names = {normalize_skill(s.name) for s in base.skills}
        moved = [r for r in requirements if normalize_skill(r["name"]) in skill_names]
        changes.append(
            ResumeChange(
                resume_id=resume.id,
                change_type="skills_order",
                target_id="skills",
                target_label="Skills",
                before_text="\n".join(s.name for s in base.skills),
                after_text="\n".join(new_order),
                rationale="Moved the skills this posting asks for to the front. Nothing is added "
                "or removed — it only changes the order.",
                addresses=[{"requirement": r["name"], "quote": r["quote"]} for r in moved],
                position=position,
            )
        )

    db.add_all(changes)
    resume.base = base.to_json()
    resume.requirements = requirements
    resume.gaps = find_gaps(base, required_names, preferred_names)
    resume.dropped = dropped
    resume.profile_stamp = base.stamp()
    resume.status = "completed"
    resume.error = None
    await db.flush()

    await log_action(
        db,
        user_id=user_id,
        action="career.resume.tailored",
        risk_level="green",
        summary=f"Drafted tailoring changes for a resume: {len(changes)} suggested.",
        evidence={
            "suggested": len(changes),
            "discarded_unsupported": len(dropped),
            "gaps": len(resume.gaps),
        },
        resource_type="job_posting",
        resource_id=job.id,
    )


async def load_changes(db: AsyncSession, resume_id: uuid.UUID) -> list[ResumeChange]:
    return list(
        (
            await db.execute(
                select(ResumeChange)
                .where(ResumeChange.resume_id == resume_id)
                .order_by(ResumeChange.position, ResumeChange.created_at)
            )
        )
        .scalars()
        .all()
    )


def render_current(resume: TailoredResume, changes: list[ResumeChange]) -> str:
    """The resume as it stands: the base with only the accepted changes applied."""
    if not resume.base:
        return ""
    return render_markdown(apply_accepted(ResumeBase.from_json(resume.base), changes))


async def decide_change(
    db: AsyncSession,
    resume: TailoredResume,
    change: ResumeChange,
    *,
    decision: str,
    user_id: uuid.UUID,
) -> None:
    change.decision = decision
    change.decided_at = None if decision == "pending" else datetime.now(UTC)
    await db.flush()
    await log_action(
        db,
        user_id=user_id,
        action=f"career.resume.change_{decision}",
        risk_level="green",
        summary=f"Marked a tailoring change to '{change.target_label}' as {decision}.",
        resource_type="tailored_resume",
        resource_id=resume.id,
        evidence={"change_type": change.change_type, "target": change.target_id},
    )
