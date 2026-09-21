import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.profile.models import EMBEDDING_DIM

# Query lifecycle: pending -> running -> completed | failed. Never skipped or silently retried.
QUERY_STATUSES = ("pending", "running", "completed", "failed")

# Source-tier hierarchy, highest-trust first. Rule-based assignment lives in
# app/research/tiers.py — never LLM-assigned, since this is a trust/policy decision.
SOURCE_TIERS = (
    "official",
    "government",
    "docs",
    "reputable_secondary",
    "forum_anecdotal",
    "unknown",
)

# A claim's status reflects what the *stored* citations actually support, not what the
# extraction model claims about itself.
CLAIM_STATUSES = ("corroborated", "single_source", "contradicted", "unverified")

CITATION_STANCES = ("supports", "contradicts", "context_only")


class ResearchQuery(Base):
    __tablename__ = "research_queries"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    purpose: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    query_sources: Mapped[list["ResearchQuerySource"]] = relationship(
        back_populates="query", cascade="all, delete-orphan"
    )
    claims: Mapped[list["ResearchClaim"]] = relationship(
        back_populates="query", cascade="all, delete-orphan"
    )
    report: Mapped["ResearchReport | None"] = relationship(
        back_populates="query", cascade="all, delete-orphan", uselist=False
    )


class ResearchSource(Base):
    """Deduplicated by normalized URL and independent of any one query, so a source fetched
    for one query is reused (not re-fetched) if a later query cites the same page."""

    __tablename__ = "research_sources"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    normalized_url: Mapped[str] = mapped_column(String(2048), unique=True, nullable=False)
    original_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    domain: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(String(500))
    tier: Mapped[str] = mapped_column(String(20), default="unknown", nullable=False)
    tier_rationale: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    http_status: Mapped[int | None] = mapped_column(Integer)
    fetch_error: Mapped[str | None] = mapped_column(String(500))
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    citations: Mapped[list["ResearchClaimCitation"]] = relationship(back_populates="source")

    @property
    def is_verified(self) -> bool:
        """Deterministic pass/fail: fetched successfully and has non-trivial extracted text.
        Set by app.research.verify.verify_source at collect time; re-derivable here for
        anything that reads a source row without having gone through that step."""
        return (
            self.http_status == 200
            and self.fetch_error is None
            and self.content is not None
            and len(self.content.strip()) >= 200
        )


class ResearchQuerySource(Base):
    """Which sources a given query pulled in, and at what search rank — kept separate from
    ResearchSource so a source's fetch history is shared but each query's usage of it isn't."""

    __tablename__ = "research_query_sources"
    __table_args__ = (UniqueConstraint("query_id", "source_id", name="uq_query_source"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    query_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("research_queries.id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("research_sources.id", ondelete="CASCADE"), nullable=False
    )
    search_rank: Mapped[int | None] = mapped_column(Integer)
    search_snippet: Mapped[str | None] = mapped_column(Text)
    # Set when semantic dedup collapses this source into an already-collected one for the
    # same query (e.g. a syndicated copy of the same press release) — the row is kept for
    # audit (what was found) but excluded from extraction as an independent source.
    is_duplicate_of_source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("research_sources.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    query: Mapped[ResearchQuery] = relationship(back_populates="query_sources")
    source: Mapped[ResearchSource] = relationship(foreign_keys=[source_id])


class ResearchClaim(Base):
    """One atomic, evidence-backed fact. Append-only per query — a re-run doesn't overwrite
    a prior claim, it produces a new row, the same way SkillVersion never mutates history."""

    __tablename__ = "research_claims"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    query_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("research_queries.id", ondelete="CASCADE"), nullable=False
    )
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    claim_type: Mapped[str | None] = mapped_column(String(50))
    value: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="unverified", nullable=False)
    confidence_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    confidence_rationale: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    query: Mapped[ResearchQuery] = relationship(back_populates="claims")
    citations: Mapped[list["ResearchClaimCitation"]] = relationship(
        back_populates="claim", cascade="all, delete-orphan"
    )


class ResearchClaimCitation(Base):
    """The literal citation: a claim is only as trustworthy as the rows here. A claim with
    zero rows where excerpt_verified is true has no real evidence and must read as
    "unverified" / "I don't know", never as an assertion."""

    __tablename__ = "research_claim_citations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    claim_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("research_claims.id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("research_sources.id", ondelete="CASCADE"), nullable=False
    )
    excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    stance: Mapped[str] = mapped_column(String(20), default="supports", nullable=False)
    # Plain-code substring check that `excerpt` actually appears in the source's stored
    # content — the guardrail against a hallucinated or misattributed quote.
    excerpt_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    claim: Mapped[ResearchClaim] = relationship(back_populates="citations")
    source: Mapped[ResearchSource] = relationship(back_populates="citations")


class ResearchReport(Base):
    """The synthesized answer for a query. `summary` is assembled from claim-linked bullets
    (see app/research/report.py); `uncertainties` are gaps stated explicitly, never papered
    over with a confident-sounding guess."""

    __tablename__ = "research_reports"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    query_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("research_queries.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    uncertainties: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    claim_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    model_used: Mapped[str | None] = mapped_column(String(100))
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    query: Mapped[ResearchQuery] = relationship(back_populates="report")


class ResearchEmbedding(Base):
    """Mirrors ProfileEmbedding's polymorphic shape so Phase 4's cross-corpus search can
    point a result straight back to a real source or claim row, not a floating text blob.
    owner_type is "source_chunk" (owner_id -> ResearchSource.id) or "claim"
    (owner_id -> ResearchClaim.id)."""

    __tablename__ = "research_embeddings"
    __table_args__ = (Index("ix_research_embeddings_owner", "owner_type", "owner_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    query_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("research_queries.id", ondelete="CASCADE"), nullable=False
    )
    owner_type: Mapped[str] = mapped_column(String(50), nullable=False)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
