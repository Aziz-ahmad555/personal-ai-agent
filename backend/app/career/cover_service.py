"""Cover-letter drafting orchestration. Green risk: it reads the user's own profile and a posting
and writes a local draft — nothing is sent anywhere, and nothing reaches the export until the
user accepts it paragraph by paragraph. Logged to the audit trail.

Flow: assemble the base resume from the profile -> get the posting's verified requirements ->
one LLM call writing the letter as cited sentences -> plain-code fact-check of every sentence
(anything unsupported is dropped, and reported) -> persist paragraphs for review.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import log_action
from app.career.cover_llm import draft_letter
from app.career.cover_render import render_letter
from app.career.cover_verify import VerifyContext, verify_sentence
from app.career.models import (
    COVER_PARAGRAPH_ROLES,
    CoverLetter,
    CoverLetterParagraph,
    JobPosting,
)
from app.career.resume_base import ResumeBase
from app.career.resume_service import load_base_resume, requirements_for
from app.career.resume_verify import find_gaps
from app.config import get_settings
from app.logging import get_logger
from app.research.llm import LLMError, get_llm_provider

logger = get_logger(__name__)

# Same reasoning as the match and resume timeouts: a healthy run can take minutes under provider
# overload, but a background task dies with the server, so past this the run is presumed dead.
LETTER_TIMEOUT = timedelta(minutes=10)
STALLED_MESSAGE = (
    "This draft didn't finish — the server was probably restarted while it was working. Try again."
)


class CoverLetterError(RuntimeError):
    """The letter couldn't be drafted at all; the message is shown to the user as-is."""


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def is_stalled(letter: CoverLetter, *, now: datetime | None = None) -> bool:
    if letter.status != "running":
        return False
    return (now or datetime.now(UTC)) - _as_utc(letter.started_at) > LETTER_TIMEOUT


def effective_text(paragraph: CoverLetterParagraph) -> str:
    """The user's own edit if there is one, else the fact-checked original."""
    return paragraph.edited_text if paragraph.edited_text else paragraph.text


async def start_letter(db: AsyncSession, job: JobPosting, user_id: uuid.UUID) -> CoverLetter:
    """Creates (or resets) the row so the UI has something to poll. Regenerating discards the
    previous draft, its decisions, and any edits — the UI confirms before calling this."""
    letter = (
        await db.execute(select(CoverLetter).where(CoverLetter.job_posting_id == job.id))
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if letter is None:
        letter = CoverLetter(
            user_id=user_id, job_posting_id=job.id, status="running", started_at=now
        )
        db.add(letter)
    else:
        await db.execute(
            delete(CoverLetterParagraph).where(CoverLetterParagraph.letter_id == letter.id)
        )
        letter.status = "running"
        letter.error = None
        letter.started_at = now
        letter.base = None
        letter.requirements = []
        letter.gaps = []
        letter.dropped = []
        letter.profile_stamp = None
    await db.flush()
    return letter


async def run_letter(db: AsyncSession, job_posting_id: uuid.UUID, *, user_id: uuid.UUID) -> None:
    job = await db.get(JobPosting, job_posting_id)
    if job is None:
        logger.warning("career_job_not_found_for_letter", job_posting_id=str(job_posting_id))
        return
    letter = await start_letter(db, job, user_id)
    try:
        await _compute(db, job, letter, user_id=user_id)
    except (CoverLetterError, LLMError) as exc:
        await _fail(db, job, letter, str(exc), user_id=user_id)
    except Exception as exc:  # last-resort guardrail: a crash must still resolve the row
        logger.exception("career_cover_letter_crashed", job_posting_id=str(job_posting_id))
        await _fail(db, job, letter, f"Unexpected error: {exc}", user_id=user_id)


async def _fail(
    db: AsyncSession, job: JobPosting, letter: CoverLetter, message: str, *, user_id: uuid.UUID
) -> None:
    letter.status = "failed"
    letter.error = message
    await db.flush()
    await log_action(
        db,
        user_id=user_id,
        action="career.cover_letter.draft_failed",
        risk_level="green",
        summary="Could not draft a cover letter for a job posting.",
        resource_type="job_posting",
        resource_id=job.id,
        error=message,
    )


async def _compute(
    db: AsyncSession, job: JobPosting, letter: CoverLetter, *, user_id: uuid.UUID
) -> None:
    posting_text = (job.description_text or "").strip()
    if not posting_text:
        raise CoverLetterError(
            "This posting has no description text to write to — paste the full posting first."
        )
    base = await load_base_resume(db, user_id)
    if not (base.has_tailorable_content or base.skills):
        raise CoverLetterError(
            "Your profile has no summary, work-history descriptions, or evidence-backed skills "
            "yet, so there's nothing to write a letter from. Add some on the Profile page first."
        )

    llm = get_llm_provider(get_settings())
    requirements = await requirements_for(db, job, llm)
    if not requirements:
        raise CoverLetterError(
            "No requirements could be read from this posting, so there's nothing to write "
            "toward. Paste the full posting."
        )

    required = [r["name"] for r in requirements if r["kind"] == "required"]
    preferred = [r["name"] for r in requirements if r["kind"] == "preferred"]
    gaps = find_gaps(base, required, preferred)

    raw_paragraphs = await draft_letter(
        llm,
        base=base,
        job_title=job.title,
        company=job.company_name,
        posting_text=posting_text,
        requirements=requirements,
        unsupported_skills=[g["skill"] for g in gaps],
    )

    ctx = VerifyContext(
        base=base,
        posting_text=posting_text,
        job_title=job.title,
        company=job.company_name,
        watch_terms=list(
            dict.fromkeys(
                [r["name"] for r in requirements]
                + [s.name for s in base.skills]
                + base.unevidenced_skills
            )
        ),
    )

    paragraphs: list[CoverLetterParagraph] = []
    dropped: list[dict[str, str]] = []
    seen: set[str] = set()
    fact_count = 0

    for raw in raw_paragraphs:
        role = raw.get("role") if raw.get("role") in COVER_PARAGRAPH_ROLES else "body"
        kept: list[dict[str, Any]] = []
        for raw_sentence in raw.get("sentences") or []:
            clean, reason = verify_sentence(raw_sentence, ctx)
            shown = str(raw_sentence.get("text", "") if isinstance(raw_sentence, dict) else "")
            if clean is None:
                dropped.append({"sentence": shown.strip()[:240], "reason": reason or "unverified"})
                continue
            if clean["text"] in seen:
                continue
            seen.add(clean["text"])
            kept.append(clean)
        if not kept:
            continue
        paragraph_facts = sum(1 for s in kept if s["kind"] == "fact")
        if role == "body" and paragraph_facts == 0:
            dropped.append(
                {
                    "sentence": kept[0]["text"][:240],
                    "reason": "a body paragraph with no verified facts",
                }
            )
            continue
        fact_count += paragraph_facts
        paragraphs.append(
            CoverLetterParagraph(
                letter_id=letter.id,
                position=len(paragraphs),
                role=str(role),
                sentences=kept,
                text=" ".join(s["text"] for s in kept),
            )
        )

    if fact_count == 0:
        raise CoverLetterError(
            "A letter couldn't be written that stays within what your profile supports — every "
            "claim it tried to make was discarded. Recording evidence for more of your skills on "
            "the Profile page will help."
        )

    db.add_all(paragraphs)
    letter.base = base.to_json()
    letter.requirements = requirements
    letter.gaps = gaps
    letter.dropped = dropped
    letter.profile_stamp = base.stamp()
    letter.status = "completed"
    letter.error = None
    await db.flush()

    await log_action(
        db,
        user_id=user_id,
        action="career.cover_letter.drafted",
        risk_level="green",
        summary=f"Drafted a cover letter: {len(paragraphs)} paragraphs to review.",
        evidence={
            "paragraphs": len(paragraphs),
            "verified_facts": fact_count,
            "discarded_unsupported": len(dropped),
            "gaps": len(gaps),
        },
        resource_type="job_posting",
        resource_id=job.id,
    )


async def load_paragraphs(db: AsyncSession, letter_id: uuid.UUID) -> list[CoverLetterParagraph]:
    return list(
        (
            await db.execute(
                select(CoverLetterParagraph)
                .where(CoverLetterParagraph.letter_id == letter_id)
                .order_by(CoverLetterParagraph.position)
            )
        )
        .scalars()
        .all()
    )


def signer_name(letter: CoverLetter) -> str | None:
    return ResumeBase.from_json(letter.base).name if letter.base else None


def render_current(letter: CoverLetter, paragraphs: list[CoverLetterParagraph]) -> str:
    """The letter as it stands: accepted paragraphs only, with the user's edit where present."""
    accepted = [effective_text(p) for p in paragraphs if p.decision == "accepted"]
    return render_letter(signer_name(letter), accepted)


async def decide_paragraph(
    db: AsyncSession,
    letter: CoverLetter,
    paragraph: CoverLetterParagraph,
    *,
    decision: str,
    user_id: uuid.UUID,
) -> None:
    paragraph.decision = decision
    paragraph.decided_at = None if decision == "pending" else datetime.now(UTC)
    await db.flush()
    await log_action(
        db,
        user_id=user_id,
        action=f"career.cover_letter.paragraph_{decision}",
        risk_level="green",
        summary=f"Marked a cover-letter paragraph as {decision}.",
        resource_type="cover_letter",
        resource_id=letter.id,
        evidence={"position": paragraph.position, "role": paragraph.role},
    )


async def edit_paragraph(
    db: AsyncSession,
    letter: CoverLetter,
    paragraph: CoverLetterParagraph,
    *,
    text: str | None,
    user_id: uuid.UUID,
) -> None:
    """Stores the user's own wording. It's theirs, so it isn't fact-checked — the API and UI say
    so. Passing None restores the fact-checked original. The audit trail records *that* an edit
    happened, not the text."""
    cleaned = (text or "").strip()
    paragraph.edited_text = cleaned or None
    await db.flush()
    await log_action(
        db,
        user_id=user_id,
        action="career.cover_letter.paragraph_edited",
        risk_level="green",
        summary=(
            "Edited a cover-letter paragraph (not fact-checked)."
            if cleaned
            else "Restored a cover-letter paragraph to its fact-checked original."
        ),
        resource_type="cover_letter",
        resource_id=letter.id,
        evidence={"position": paragraph.position, "restored": not cleaned},
    )
