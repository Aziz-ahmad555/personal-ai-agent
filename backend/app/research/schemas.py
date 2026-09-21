import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

QueryStatus = Literal["pending", "running", "completed", "failed"]
SourceTier = Literal[
    "official", "government", "docs", "reputable_secondary", "forum_anecdotal", "unknown"
]
ClaimStatus = Literal["corroborated", "single_source", "contradicted", "unverified"]
CitationStance = Literal["supports", "contradicts", "context_only"]


class ResearchQueryCreate(BaseModel):
    query_text: str = Field(min_length=1, max_length=2000)
    purpose: str | None = Field(default=None, max_length=500)


class ResearchQueryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    query_text: str
    purpose: str | None
    status: QueryStatus
    error: str | None
    created_at: datetime
    completed_at: datetime | None


class SourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    original_url: str
    domain: str
    title: str | None
    tier: SourceTier
    tier_rationale: str
    http_status: int | None
    fetch_error: str | None
    fetched_at: datetime | None
    published_at: datetime | None


class CitationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_id: uuid.UUID
    excerpt: str
    stance: CitationStance
    excerpt_verified: bool


class ClaimRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    claim_text: str
    claim_type: str | None
    value: dict[str, Any] | None
    status: ClaimStatus
    confidence_score: int
    confidence_rationale: str
    citations: list[CitationRead]


class ReportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    summary: str
    uncertainties: list[str]
    claim_ids: list[str]
    model_used: str | None
    generated_at: datetime


class ResearchQueryDetail(ResearchQueryRead):
    sources: list[SourceRead]
    claims: list[ClaimRead]
    report: ReportRead | None
