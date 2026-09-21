import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

SourceChannel = Literal["manual_url", "manual_paste", "greenhouse", "lever", "ashby", "usajobs"]
RemoteType = Literal["remote", "hybrid", "onsite", "unknown"]
Board = Literal["greenhouse", "lever", "ashby", "usajobs"]
EmployerVerificationStatus = Literal["verified", "unconfirmed", "suspicious"]
FraudRiskLevel = Literal["low", "medium", "high"]
MatchStatus = Literal["running", "completed", "failed"]
ComponentStatus = Literal["assessed", "not_assessed"]
DealBreakerCheck = Literal["none_set", "checked", "unavailable"]


class FraudSignalRead(BaseModel):
    code: str
    description: str


class EmployerVerificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employer_key: str
    verification_status: EmployerVerificationStatus
    confidence_score: int
    rationale: str
    checked_at: datetime


class JobFraudAssessmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    risk_level: FraudRiskLevel
    risk_score: int
    signals: list[FraudSignalRead]
    assessed_at: datetime


class MatchComponentRead(BaseModel):
    key: str
    label: str
    weight: int
    status: ComponentStatus
    fraction: float | None
    points: float | None
    summary: str
    reason: str | None
    details: list[dict[str, Any]]


class DealBreakerHitRead(BaseModel):
    deal_breaker: str
    quote: str


class JobMatchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: MatchStatus
    error: str | None
    # Null (never 0) when nothing could be assessed.
    score_percent: int | None
    # Of the 100 points, how many were actually measurable — the basis of low_confidence.
    assessed_weight: int
    low_confidence: bool
    components: list[MatchComponentRead]
    uncertainties: list[str]
    deal_breaker_check: DealBreakerCheck
    deal_breaker_hits: list[DealBreakerHitRead]
    # True when the profile changed after this was computed. Set by the router (it needs the
    # current profile), not read from the row.
    is_stale: bool = False
    computed_at: datetime


class JobPostingCreateFromUrl(BaseModel):
    url: HttpUrl


class JobPostingCreateFromText(BaseModel):
    raw_text: str = Field(min_length=1, max_length=20_000)


class JobPostingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_channel: SourceChannel
    external_id: str | None
    source_url: str | None
    company_name: str | None
    company_domain: str | None
    title: str | None
    location: str | None
    remote_type: RemoteType
    salary_min: int | None
    salary_max: int | None
    salary_currency: str | None
    description_text: str | None
    posted_at: datetime | None
    discovered_at: datetime
    # Populated only after POST .../verify has run — null (never a fabricated placeholder)
    # until then, and cached per-employer so this reflects the shared verification, not a
    # per-posting one.
    employer_verification: EmployerVerificationRead | None = None
    fraud_assessment: JobFraudAssessmentRead | None = None
    match: JobMatchRead | None = None


class JobBoardFeedCreate(BaseModel):
    board: Board
    company_slug: str | None = Field(default=None, max_length=200)
    keyword: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _check_identifier(self) -> "JobBoardFeedCreate":
        if self.board == "usajobs":
            if not self.keyword:
                raise ValueError("usajobs feeds require a keyword.")
        elif not self.company_slug:
            raise ValueError(f"{self.board} feeds require a company_slug.")
        return self


class JobBoardFeedRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    board: Board
    company_slug: str | None
    keyword: str | None
    is_active: bool
    last_polled_at: datetime | None
    last_poll_error: str | None
