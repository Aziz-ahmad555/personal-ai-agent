import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

ResumeStatus = Literal["running", "completed", "failed"]
ResumeChangeType = Literal["rewrite", "skills_order"]
ResumeDecisionValue = Literal["pending", "accepted", "rejected"]


class ResumeAddressRead(BaseModel):
    """A posting requirement a change speaks to, with the verified quote from the posting."""

    requirement: str
    quote: str


class ResumeChangeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    change_type: ResumeChangeType
    target_id: str
    target_label: str
    before_text: str
    after_text: str
    rationale: str
    addresses: list[ResumeAddressRead]
    decision: ResumeDecisionValue
    position: int


class ResumeGapRead(BaseModel):
    skill: str
    kind: Literal["required", "preferred"]
    reason: str


class ResumeDroppedRead(BaseModel):
    source: str
    reason: str


class ResumeCounts(BaseModel):
    accepted: int = 0
    rejected: int = 0
    pending: int = 0


class TailoredResumeRead(BaseModel):
    id: uuid.UUID
    job_posting_id: uuid.UUID
    status: ResumeStatus
    error: str | None
    # True when the profile changed after this draft was made; regenerate to reflect it.
    is_stale: bool = False
    started_at: datetime
    changes: list[ResumeChangeRead] = []
    # Required/preferred skills with no evidence in the profile. Shown, never written in.
    gaps: list[ResumeGapRead] = []
    # Proposals discarded because they added claims the profile doesn't support.
    dropped: list[ResumeDroppedRead] = []
    counts: ResumeCounts = ResumeCounts()
    # The resume as it stands: original wording plus only the accepted changes.
    preview_markdown: str = ""


class ResumeDecision(BaseModel):
    decision: ResumeDecisionValue


class ResumeExport(BaseModel):
    filename: str
    markdown: str
    accepted: int
    pending: int
    rejected: int
