import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.career.resume_schemas import ResumeDecisionValue, ResumeGapRead

CoverStatus = Literal["running", "completed", "failed"]
CoverRole = Literal["opening", "body", "closing"]
SentenceKind = Literal["fact", "framing"]
SupportType = Literal["profile_experience", "profile_skill", "profile_summary", "posting_quote"]


class CoverSupportRead(BaseModel):
    """What a sentence was checked against: a role, an evidence-backed skill, the summary, or a
    verbatim excerpt from the posting."""

    type: SupportType
    ref: str
    label: str
    excerpt: str


class CoverSentenceRead(BaseModel):
    text: str
    kind: SentenceKind
    supports: list[CoverSupportRead]


class CoverParagraphRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    position: int
    role: CoverRole
    # The fact-checked original.
    text: str
    # The user's own rewrite, if any. It is their words, so it is NOT fact-checked.
    edited_text: str | None
    is_edited: bool = False
    sentences: list[CoverSentenceRead]
    decision: ResumeDecisionValue


class CoverDroppedRead(BaseModel):
    sentence: str
    reason: str


class CoverCounts(BaseModel):
    accepted: int = 0
    rejected: int = 0
    pending: int = 0


class CoverLetterRead(BaseModel):
    id: uuid.UUID
    job_posting_id: uuid.UUID
    status: CoverStatus
    error: str | None
    is_stale: bool = False
    started_at: datetime
    paragraphs: list[CoverParagraphRead] = []
    gaps: list[ResumeGapRead] = []
    # Sentences discarded because the profile or posting didn't support them.
    dropped: list[CoverDroppedRead] = []
    counts: CoverCounts = CoverCounts()
    # The letter as it stands: accepted paragraphs only, using the user's edit where there is one.
    preview_text: str = ""


class CoverDecision(BaseModel):
    decision: ResumeDecisionValue


class CoverEdit(BaseModel):
    """null (or empty) restores the fact-checked original."""

    text: str | None = Field(default=None, max_length=4000)


class CoverExport(BaseModel):
    filename: str
    text: str
    accepted: int
    pending: int
    rejected: int
    # How many included paragraphs are the user's own wording, and so not fact-checked.
    edited: int
