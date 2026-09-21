"""Employer verification and fraud assessment for a job posting.

Employer verification reuses the Research Engine's full pipeline (a targeted research
query asking whether the claimed employer is real) rather than standing up a parallel
research mechanism — see app.research.pipeline.run_research_query. It's cached per
employer, not per posting, so many postings from the same company share one research run
(EMPLOYER_VERIFICATION_FRESHNESS controls the re-check interval, the same idea as the
pipeline's own SOURCE_FRESHNESS). The verdict — verified / unconfirmed / suspicious — is
then derived by plain code from that pipeline's already-scored claims and source tiers
re-classified with the employer's claimed domain (app.research.tiers.classify_domain
already supports this via its employer_domains parameter; the shared pipeline can't pass
it at collect time since it doesn't yet know which domain is "confirmed", so that
classification happens here instead, without mutating the stored, context-free source
row). No second LLM call decides the verdict.

Fraud assessment (app.career.fraud) is pure and deterministic; this module just wires its
result, plus the employer verification's status, into a stored JobFraudAssessment.

Both steps are Green risk — nothing external happens, only reading and analyzing — and
both are logged to the audit trail via app.audit.service, same as job discovery.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.audit.service import log_action
from app.career.fraud import assess_fraud_risk
from app.career.models import EmployerVerification, JobFraudAssessment, JobPosting
from app.logging import get_logger
from app.research.models import ResearchClaim, ResearchClaimCitation, ResearchQuery
from app.research.pipeline import run_research_query
from app.research.scoring import score_claim
from app.research.tiers import TIER_RANK, classify_domain

logger = get_logger(__name__)

EMPLOYER_VERIFICATION_FRESHNESS = timedelta(days=30)
MIN_CONFIDENCE_FOR_VERIFIED = 40


def employer_key_for(*, company_name: str | None, company_domain: str | None) -> str | None:
    """Normalized cache key: the registrable domain when known (most reliable — two
    postings claiming the same domain are almost certainly the same employer), else the
    lowercased company name. None when neither is present — nothing to verify against."""
    if company_domain:
        return company_domain.strip().lower().removeprefix("www.")
    if company_name:
        return f"name:{company_name.strip().lower()}"
    return None


def _as_utc(value: datetime) -> datetime:
    """See app.research.pipeline._as_utc — SQLite (tests) drops tzinfo on round-trip."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _as_of(source_fetched_at: datetime | None) -> float | None:
    if source_fetched_at is None:
        return None
    return (datetime.now(UTC) - _as_utc(source_fetched_at)).total_seconds() / 86400


async def _derive_verdict(
    db: AsyncSession, query: ResearchQuery, *, company_domain: str | None
) -> tuple[str, int, str]:
    """Re-scores each claim using classify_domain with this employer's claimed domain —
    the generic pipeline's own claim.confidence_score was computed blind to that (an
    unrecognized custom domain scores as "unknown" tier there), so trusting it directly
    would make "verified" nearly unreachable for a real employer whose domain simply isn't
    in the curated allowlists. Reusing score_claim here (not reinventing scoring) keeps
    this consistent with Phase 3's formula, just fed the employer-aware tier."""
    if query.status == "failed" or query.error:
        return (
            "unconfirmed",
            0,
            f"Research could not be completed: {query.error or 'unknown error'}.",
        )

    claims = (
        (
            await db.execute(
                select(ResearchClaim)
                .where(ResearchClaim.query_id == query.id)
                .options(
                    selectinload(ResearchClaim.citations).selectinload(
                        ResearchClaimCitation.source
                    )
                )
            )
        )
        .scalars()
        .all()
    )
    if not claims:
        return "unconfirmed", 0, "No claims were extracted researching this employer."

    employer_domains = {company_domain} if company_domain else None
    best_confidence = 0
    has_official_source = False
    has_contradiction = False

    for claim in claims:
        if claim.status == "contradicted":
            has_contradiction = True

        supporting = [
            citation
            for citation in claim.citations
            if citation.stance == "supports" and citation.excerpt_verified
        ]
        if not supporting:
            continue

        domains_seen: set[str] = set()
        best_tier = "unknown"
        newest_age_days: float | None = None
        for citation in supporting:
            source = citation.source
            tier, _ = classify_domain(source.domain, employer_domains=employer_domains)
            if tier in ("official", "government"):
                has_official_source = True
            if TIER_RANK.get(tier, 0) > TIER_RANK.get(best_tier, 0):
                best_tier = tier
            domains_seen.add(source.domain)
            age = _as_of(source.fetched_at)
            if age is not None and (newest_age_days is None or age < newest_age_days):
                newest_age_days = age

        rescored = score_claim(
            best_tier=best_tier,
            independent_corroborations=len(domains_seen),
            all_citations_verified=all(c.excerpt_verified for c in claim.citations),
            has_contradiction=claim.status == "contradicted",
            newest_source_age_days=newest_age_days,
        )
        best_confidence = max(best_confidence, rescored.confidence_score)

    if has_contradiction:
        return (
            "suspicious",
            best_confidence,
            "Research found at least one source actively contradicting this employer's "
            "legitimacy.",
        )

    if has_official_source and best_confidence >= MIN_CONFIDENCE_FOR_VERIFIED:
        return (
            "verified",
            best_confidence,
            "Research found an official/government source for this employer, with "
            f"re-scored confidence {best_confidence}/100.",
        )

    return (
        "unconfirmed",
        best_confidence,
        "Research found no official/government source confirming this employer, or "
        "confidence was too low to treat it as verified.",
    )


async def verify_employer(
    db: AsyncSession, job_posting: JobPosting, *, user_id: uuid.UUID
) -> EmployerVerification:
    employer_key = employer_key_for(
        company_name=job_posting.company_name, company_domain=job_posting.company_domain
    )
    if employer_key is None:
        raise ValueError(
            "Cannot verify an employer with neither a company_name nor a company_domain."
        )

    existing = (
        await db.execute(
            select(EmployerVerification).where(EmployerVerification.employer_key == employer_key)
        )
    ).scalar_one_or_none()
    if existing is not None and (
        datetime.now(UTC) - _as_utc(existing.checked_at) < EMPLOYER_VERIFICATION_FRESHNESS
    ):
        return existing

    query = ResearchQuery(
        user_id=user_id,
        query_text=(
            f"Is '{job_posting.company_name}' a real, legitimate employer, and what is "
            "their official corporate website?"
        ),
        purpose="career.employer_verification",
    )
    db.add(query)
    await db.flush()

    await run_research_query(db, query.id)
    await db.refresh(query)

    status_, confidence, rationale = await _derive_verdict(
        db, query, company_domain=job_posting.company_domain
    )

    verification = existing or EmployerVerification(employer_key=employer_key)
    verification.company_name = job_posting.company_name
    verification.company_domain = job_posting.company_domain
    verification.research_query_id = query.id
    verification.verification_status = status_
    verification.confidence_score = confidence
    verification.rationale = rationale
    verification.checked_at = datetime.now(UTC)
    if existing is None:
        db.add(verification)
    await db.flush()

    await log_action(
        db,
        user_id=user_id,
        action="career.employer.verified",
        risk_level="green",
        summary=f"Verified employer '{job_posting.company_name}': {status_}.",
        evidence={"employer_key": employer_key, "confidence_score": confidence},
        resource_type="employer_verification",
        resource_id=verification.id,
        result={"verification_status": status_},
    )
    return verification


async def assess_job_fraud(
    db: AsyncSession,
    job_posting: JobPosting,
    *,
    employer_verification: EmployerVerification | None,
    user_id: uuid.UUID,
) -> JobFraudAssessment:
    result = assess_fraud_risk(
        description_text=job_posting.description_text,
        salary_min=job_posting.salary_min,
        salary_max=job_posting.salary_max,
        company_domain=job_posting.company_domain,
        source_url=job_posting.source_url,
        source_channel=job_posting.source_channel,
        employer_verification_status=(
            employer_verification.verification_status if employer_verification else None
        ),
    )

    existing = (
        await db.execute(
            select(JobFraudAssessment).where(
                JobFraudAssessment.job_posting_id == job_posting.id
            )
        )
    ).scalar_one_or_none()

    assessment = existing or JobFraudAssessment(job_posting_id=job_posting.id)
    assessment.risk_level = result.risk_level
    assessment.risk_score = result.risk_score
    assessment.signals = [
        {"code": signal.code, "description": signal.description} for signal in result.signals
    ]
    assessment.employer_verification_id = (
        employer_verification.id if employer_verification else None
    )
    assessment.assessed_at = datetime.now(UTC)
    if existing is None:
        db.add(assessment)
    await db.flush()

    await log_action(
        db,
        user_id=user_id,
        action="career.job.fraud_assessed",
        risk_level="green",
        summary=f"Assessed fraud risk for job posting: {result.risk_level}.",
        evidence={
            "risk_score": result.risk_score,
            "signals": [signal.code for signal in result.signals],
        },
        resource_type="job_posting",
        resource_id=job_posting.id,
        result={"risk_level": result.risk_level},
    )
    return assessment


async def verify_and_assess_job(
    db: AsyncSession, job_posting_id: uuid.UUID, *, user_id: uuid.UUID
) -> None:
    """Entry point for the background task: verifies the employer (if there's enough
    identifying info to do so) then always runs fraud assessment, folding in whatever
    verification status resulted — never blocking fraud assessment on verification
    succeeding, since a posting with no identifiable employer at all is itself worth
    assessing (and is exactly the kind of posting fraud signals matter most for)."""
    job_posting = await db.get(JobPosting, job_posting_id)
    if job_posting is None:
        logger.warning("career_job_not_found_for_verification", job_posting_id=str(job_posting_id))
        return

    employer_verification: EmployerVerification | None = None
    try:
        employer_verification = await verify_employer(db, job_posting, user_id=user_id)
    except ValueError:
        employer_verification = None

    await assess_job_fraud(
        db, job_posting, employer_verification=employer_verification, user_id=user_id
    )
