import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# manual_url / manual_paste: the user pointed at or pasted a specific posting — always
# in-scope regardless of source, since the user themselves is the authorized channel.
# greenhouse / lever / ashby / usajobs: public, documented job-board APIs companies
# publish for third-party consumption. LinkedIn/Indeed are deliberately absent — those
# need an official partner/publisher API agreement (CLAUDE.md Phase 7), and are never
# scraped regardless of phase.
SOURCE_CHANNELS = ("manual_url", "manual_paste", "greenhouse", "lever", "ashby", "usajobs")
JOB_BOARDS = ("greenhouse", "lever", "ashby", "usajobs")
REMOTE_TYPES = ("remote", "hybrid", "onsite", "unknown")

# Deliberately not ResearchClaim.status's vocabulary — this answers a different question
# ("is this employer real") and reusing the word would blur the two. Assigned by plain
# code in app.career.verification, never by the LLM step inside the research pipeline it
# reuses.
EMPLOYER_VERIFICATION_STATUSES = ("verified", "unconfirmed", "suspicious")

# A *content* risk label (is this posting's text suspicious), distinct from audit's
# Green/Yellow/Red *action* risk level — the two answer different questions and must
# never be conflated.
FRAUD_RISK_LEVELS = ("low", "medium", "high")


class JobPosting(Base):
    """One discovered posting. `research_source_id` links a fetched page into the Research
    Engine's own dedup universe (app.research.dedupe) rather than a parallel one, so a job
    posting's page is treated the same as any other researched source. Every field beyond
    the identifying ones is nullable: absence is recorded as None, never guessed at by
    extraction (see app.career.extraction) — CLAUDE.md: "if evidence isn't available, the
    system says I don't know."""

    __tablename__ = "job_postings"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "source_channel", "external_id", name="uq_job_postings_user_channel_external"
        ),
        UniqueConstraint("user_id", "source_url", name="uq_job_postings_user_source_url"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    source_channel: Mapped[str] = mapped_column(String(20), nullable=False)
    # Board-specific job id, when the channel provides one (all board channels do; manual
    # capture never does).
    external_id: Mapped[str | None] = mapped_column(String(200))
    source_url: Mapped[str | None] = mapped_column(String(2048))

    company_name: Mapped[str | None] = mapped_column(String(255))
    company_domain: Mapped[str | None] = mapped_column(String(255))
    title: Mapped[str | None] = mapped_column(String(255))
    location: Mapped[str | None] = mapped_column(String(255))
    remote_type: Mapped[str] = mapped_column(String(20), default="unknown", nullable=False)
    salary_min: Mapped[int | None] = mapped_column(Integer)
    salary_max: Mapped[int | None] = mapped_column(Integer)
    salary_currency: Mapped[str | None] = mapped_column(String(10))

    description_text: Mapped[str | None] = mapped_column(Text)
    description_hash: Mapped[str | None] = mapped_column(String(64), index=True)

    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    research_source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("research_sources.id", ondelete="SET NULL")
    )
    # The board API's raw response for this job, kept for audit/reprocessing — never the
    # source of truth for the structured columns above, which are what the app reads.
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class JobBoardFeed(Base):
    """A user-configured subscription to one company's postings on a public job-board API
    (Greenhouse/Lever/Ashby), or a keyword search on USAJobs. These APIs answer "give me
    company X's jobs" (or, for USAJobs, "search this keyword"), not "search the whole
    web" — discovery beyond manual capture starts from a list the user curates, never a
    crawl."""

    __tablename__ = "job_board_feeds"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "board", "company_slug", "keyword", name="uq_job_board_feed_user"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    board: Mapped[str] = mapped_column(String(20), nullable=False)
    # Greenhouse/Lever/Ashby: the company's board slug. Null for usajobs.
    company_slug: Mapped[str | None] = mapped_column(String(200))
    # USAJobs: the search keyword. Null for company-slug boards.
    keyword: Mapped[str | None] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_poll_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class EmployerVerification(Base):
    """Cached per employer, not per posting, so many postings from the same company share
    one research run — see app.career.verification.EMPLOYER_VERIFICATION_FRESHNESS for the
    re-check interval. Reuses the Research Engine's own pipeline (app.research.pipeline)
    rather than a parallel research mechanism; verification_status is then derived by
    plain code from that pipeline's already-scored claims and re-classified source tiers,
    never by a second LLM call."""

    __tablename__ = "employer_verifications"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Normalized: the registrable company_domain when known, else "name:<lowercased
    # company_name>" — see app.career.verification.employer_key_for.
    employer_key: Mapped[str] = mapped_column(String(300), unique=True, nullable=False, index=True)
    company_name: Mapped[str | None] = mapped_column(String(255))
    company_domain: Mapped[str | None] = mapped_column(String(255))

    research_query_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("research_queries.id", ondelete="SET NULL")
    )

    verification_status: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Templated from the same computed facts that produced verification_status — never a
    # second LLM call re-describing its own conclusion (mirrors app.research.scoring).
    rationale: Mapped[str] = mapped_column(Text, nullable=False)

    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class JobFraudAssessment(Base):
    """One per JobPosting — fraud signals are about a specific posting's text/fields, not
    the employer as a whole (that's EmployerVerification). Deterministic and rule-based
    (see app.career.fraud) — never an LLM judgment, per CLAUDE.md's "no LLM for ...
    policy enforcement" rule."""

    __tablename__ = "job_fraud_assessments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    job_posting_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("job_postings.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    risk_level: Mapped[str] = mapped_column(String(10), nullable=False)
    risk_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # [{"code": ..., "description": ...}], one entry per signal that actually fired — a
    # "high" verdict is always traceable to specific, inspectable reasons.
    signals: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    employer_verification_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("employer_verifications.id", ondelete="SET NULL")
    )
    assessed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


MATCH_STATUSES = ("running", "completed", "failed")


class JobMatch(Base):
    """One per JobPosting: how well the posting fits the user's profile, as a weighted,
    fully-decomposed score (see app.career.matching). Every component carries its evidence,
    and a component that couldn't be judged (the posting or the profile doesn't say) is
    recorded as "not_assessed" and left out of the score's denominator — never guessed.
    `assessed_weight` is how much of the 100 points was actually measurable, which is what
    the UI's low-confidence warning keys off."""

    __tablename__ = "job_matches"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    job_posting_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("job_postings.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), default="running", nullable=False)
    error: Mapped[str | None] = mapped_column(Text)

    # Null when nothing at all could be assessed — an honest "I can't tell", not a 0.
    score_percent: Mapped[int | None] = mapped_column(Integer)
    assessed_weight: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    low_confidence: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Per-component breakdown: [{key, label, weight, status, fraction, points, summary,
    # reason, details}] — see app.career.matching.ComponentResult.
    components: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    uncertainties: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    # The verified requirements the score was computed from (quotes confirmed to appear in
    # the posting), kept so the breakdown is auditable after the fact.
    requirements: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    # "none_set" (no deal-breakers in preferences), "checked", or "unavailable" (the check
    # itself failed — the user must not read an empty hit list as "clear" in that case).
    deal_breaker_check: Mapped[str] = mapped_column(String(20), default="none_set", nullable=False)
    deal_breaker_hits: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False
    )

    # Hash of the profile facts this score was computed from — a differing current hash
    # means the profile changed since, i.e. the score is stale.
    profile_stamp: Mapped[str | None] = mapped_column(String(64))
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
