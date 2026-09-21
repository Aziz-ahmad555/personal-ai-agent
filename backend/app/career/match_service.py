"""Orchestrates one job-to-profile match: read the posting into verified requirements (LLM),
load the candidate's profile facts, find embedding-similar skills for anything not matched
exactly, score in plain code (app.career.matching), and persist the fully-decomposed result.

Green risk — nothing leaves the system, it only reads the posting and the user's own
profile. Logged to the audit trail like the other career steps.
"""

import hashlib
import json
import math
import uuid
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.audit.service import log_action
from app.career.matching import (
    EducationFact,
    FuzzyMatch,
    JobFacts,
    PreferenceFacts,
    ProfileFacts,
    SkillFact,
    experience_years,
    normalize_skill,
    score_match,
)
from app.career.models import JobMatch, JobPosting
from app.career.requirements import (
    JobRequirements,
    check_deal_breakers,
    extract_requirements,
)
from app.config import get_settings
from app.logging import get_logger
from app.profile import embeddings
from app.profile.models import Preferences, Profile, Skill
from app.research.llm import LLMError, get_llm_provider

logger = get_logger(__name__)

# Cosine similarity at/above which a skill the posting wants, but the candidate didn't list
# under that name, is treated as "similar" (labeled, and worth only FUZZY_CREDIT). This is
# an uncalibrated starting default, not a tuned value — worth revisiting against real
# postings before trusting it.
FUZZY_SIMILARITY_THRESHOLD = 0.8


class MatchError(RuntimeError):
    """The match could not be computed at all (no description, LLM unavailable...). The
    message is shown to the user as-is, so it must say what to do."""


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


async def load_profile_facts(
    db: AsyncSession, user_id: uuid.UUID, *, today: date | None = None
) -> tuple[ProfileFacts, str]:
    """Returns the scoring inputs plus a stamp — a hash of the *raw* profile data (deliberately
    not of derived values like years-of-experience, which drift daily for an ongoing role and
    would mark every score stale overnight)."""
    today = today or date.today()

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
    prefs_row = (
        await db.execute(select(Preferences).where(Preferences.user_id == user_id))
    ).scalar_one_or_none()

    skills: list[SkillFact] = []
    unevidenced: list[str] = []
    experiences: list[tuple[date, date | None]] = []
    educations: list[EducationFact] = []
    if profile is not None:
        for skill in profile.skills:
            if not skill.versions:
                unevidenced.append(skill.name)
                continue
            latest = max(skill.versions, key=lambda v: _as_utc(v.asserted_at))
            skills.append(SkillFact(name=skill.name, level=latest.level, evidence=latest.evidence))
        experiences = [(e.start_date, e.end_date) for e in profile.experiences]
        educations = [EducationFact(degree=e.degree, field=e.field) for e in profile.educations]

    prefs = PreferenceFacts()
    if prefs_row is not None:
        prefs = PreferenceFacts(
            remote_preference=prefs_row.remote_preference,
            locations=tuple(prefs_row.locations or []),
            salary_min=prefs_row.salary_min,
            salary_max=prefs_row.salary_max,
            industries_include=tuple(prefs_row.industries_include or []),
            industries_exclude=tuple(prefs_row.industries_exclude or []),
            deal_breakers=prefs_row.deal_breakers,
        )

    facts = ProfileFacts(
        skills=tuple(skills),
        unevidenced_skill_names=tuple(unevidenced),
        experience_years=experience_years(experiences, today=today),
        educations=tuple(educations),
        preferences=prefs,
    )

    raw = {
        "skills": sorted((s.name, s.level, s.evidence) for s in skills),
        "unevidenced": sorted(unevidenced),
        "experiences": sorted(
            (start.isoformat(), end.isoformat() if end else None) for start, end in experiences
        ),
        "educations": sorted((e.degree or "", e.field or "") for e in educations),
        "preferences": {
            "remote": prefs.remote_preference,
            "locations": sorted(prefs.locations),
            "salary": [prefs.salary_min, prefs.salary_max],
            "include": sorted(prefs.industries_include),
            "exclude": sorted(prefs.industries_exclude),
            "deal_breakers": prefs.deal_breakers,
        },
    }
    stamp = hashlib.sha256(json.dumps(raw, sort_keys=True, default=str).encode()).hexdigest()
    return facts, stamp


def _cosine(a: list[float], b: list[float]) -> float:
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return sum(x * y for x, y in zip(a, b, strict=True)) / (norm_a * norm_b)


async def find_fuzzy_matches(
    requirements: JobRequirements, profile: ProfileFacts
) -> tuple[dict[str, FuzzyMatch], bool]:
    """For each requested skill with no exact/alias match, the most embedding-similar profile
    skill (if above threshold). Returns (matches keyed by normalized requirement name,
    whether similarity matching was actually available). Done in Python rather than as a
    pgvector query: it's a handful of short strings, and this keeps it backend-agnostic."""
    have = {normalize_skill(s.name) for s in profile.skills}
    wanted: dict[str, str] = {}
    for req in (*requirements.required_skills, *requirements.preferred_skills):
        norm = normalize_skill(req.name)
        if norm not in have:
            wanted.setdefault(norm, req.name)
    if not wanted or not profile.skills:
        return {}, True

    profile_names = [s.name for s in profile.skills]
    wanted_names = list(wanted.values())
    vectors = await embeddings.embed_texts(wanted_names + profile_names)
    if vectors is None:
        return {}, False

    want_vecs = vectors[: len(wanted_names)]
    profile_vecs = vectors[len(wanted_names) :]
    matches: dict[str, FuzzyMatch] = {}
    for norm, want_vec in zip(wanted, want_vecs, strict=True):
        scored = zip(profile_names, (_cosine(want_vec, vec) for vec in profile_vecs), strict=True)
        best_name, best_sim = max(scored, key=lambda pair: pair[1])
        if best_sim >= FUZZY_SIMILARITY_THRESHOLD:
            matches[norm] = FuzzyMatch(profile_skill=best_name, similarity=best_sim)
    return matches, True


async def start_match(db: AsyncSession, job: JobPosting) -> JobMatch:
    """Creates (or resets to "running") the match row, so the UI has something to poll while
    the background computation runs. A previous result's fields are kept until replaced."""
    match = (
        await db.execute(select(JobMatch).where(JobMatch.job_posting_id == job.id))
    ).scalar_one_or_none()
    if match is None:
        match = JobMatch(job_posting_id=job.id, status="running")
        db.add(match)
    else:
        match.status = "running"
        match.error = None
    await db.flush()
    return match


async def run_match(db: AsyncSession, job_posting_id: uuid.UUID, *, user_id: uuid.UUID) -> None:
    job = await db.get(JobPosting, job_posting_id)
    if job is None:
        logger.warning("career_job_not_found_for_match", job_posting_id=str(job_posting_id))
        return
    match = await start_match(db, job)

    try:
        await _compute(db, job, match, user_id=user_id)
    except (MatchError, LLMError) as exc:
        await _fail(db, job, match, str(exc), user_id=user_id)
    except Exception as exc:  # last-resort guardrail: a crash must still resolve the row
        logger.exception("career_match_crashed", job_posting_id=str(job_posting_id))
        await _fail(db, job, match, f"Unexpected error: {exc}", user_id=user_id)


async def _fail(
    db: AsyncSession, job: JobPosting, match: JobMatch, message: str, *, user_id: uuid.UUID
) -> None:
    match.status = "failed"
    match.error = message
    await db.flush()
    await log_action(
        db,
        user_id=user_id,
        action="career.job.match_failed",
        risk_level="green",
        summary="Could not compute a match for a job posting.",
        resource_type="job_posting",
        resource_id=job.id,
        error=message,
    )


async def _compute(
    db: AsyncSession, job: JobPosting, match: JobMatch, *, user_id: uuid.UUID
) -> None:
    description = (job.description_text or "").strip()
    if not description:
        raise MatchError(
            "This posting has no description text to read requirements from — paste the "
            "full posting to match it."
        )

    llm = get_llm_provider(get_settings())
    requirements = await extract_requirements(llm, description=description)
    facts, stamp = await load_profile_facts(db, user_id)
    fuzzy, similarity_available = await find_fuzzy_matches(requirements, facts)

    deal_breaker_check = "none_set"
    deal_breaker_hits: list[dict[str, str]] = []
    if facts.preferences.deal_breakers and facts.preferences.deal_breakers.strip():
        try:
            hits = await check_deal_breakers(
                llm, deal_breakers=facts.preferences.deal_breakers, description=description
            )
            deal_breaker_check = "checked"
            deal_breaker_hits = [{"deal_breaker": h.deal_breaker, "quote": h.quote} for h in hits]
        except LLMError as exc:
            logger.warning("career_deal_breaker_check_failed", error=str(exc))
            deal_breaker_check = "unavailable"

    result = score_match(
        requirements,
        facts,
        JobFacts(
            remote_type=job.remote_type,
            location=job.location,
            salary_min=job.salary_min,
            salary_max=job.salary_max,
            salary_currency=job.salary_currency,
        ),
        fuzzy=fuzzy,
    )
    uncertainties = list(result.uncertainties)
    if not similarity_available:
        uncertainties.append(
            "Similar-skill matching was unavailable (embeddings couldn't be generated), so "
            "only exact and alias skill matches were counted."
        )
    if deal_breaker_check == "unavailable":
        uncertainties.append(
            "Your deal-breakers could not be checked against this posting — don't read the "
            "absence of a warning as 'clear'."
        )

    match.status = "completed"
    match.error = None
    match.score_percent = result.score_percent
    match.assessed_weight = result.assessed_weight
    match.low_confidence = result.low_confidence
    match.components = [c.to_json() for c in result.components]
    match.uncertainties = uncertainties
    match.requirements = requirements.to_json()
    match.deal_breaker_check = deal_breaker_check
    match.deal_breaker_hits = deal_breaker_hits
    match.profile_stamp = stamp
    match.computed_at = datetime.now(UTC)
    await db.flush()

    await log_action(
        db,
        user_id=user_id,
        action="career.job.matched",
        risk_level="green",
        summary=(
            f"Matched a job posting to the profile: {result.score_percent}%"
            if result.score_percent is not None
            else "Matched a job posting to the profile: not enough information to score."
        ),
        evidence={
            "assessed_weight": result.assessed_weight,
            "low_confidence": result.low_confidence,
            "deal_breaker_hits": len(deal_breaker_hits),
        },
        resource_type="job_posting",
        resource_id=job.id,
        result={"score_percent": result.score_percent},
    )
