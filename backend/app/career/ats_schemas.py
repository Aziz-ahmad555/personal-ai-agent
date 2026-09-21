from typing import Literal

from pydantic import BaseModel

KeywordStateValue = Literal["in_context", "listed_only", "gap"]
CheckStatusValue = Literal["pass", "warn", "fail"]
ResumeSource = Literal["tailored", "profile"]

# Shown with every result: the honest limits of what this can tell you.
LIMITATIONS = [
    "No applicant-tracking vendor publishes how it scores resumes, so this checks well-known "
    "parsing pitfalls and keyword coverage — it can't tell you how a specific employer's system "
    "will rank you.",
    "Keywords are matched by name and common aliases (for example K8s for Kubernetes); some "
    "systems are stricter or looser than that.",
    "It reads the resume text this app produces. It can't see how a PDF or Word file will parse.",
]


class AtsKeywordRead(BaseModel):
    name: str
    kind: Literal["required", "preferred"]
    state: KeywordStateValue
    detail: str
    # Roles whose recorded evidence points at a skill that's only in the Skills list.
    roles: list[str] = []


class AtsKeywordStats(BaseModel):
    required_found: int
    required_total: int
    preferred_found: int
    preferred_total: int
    in_context: int
    # Null when the posting listed no skills to check, never a made-up 0 or 100.
    coverage_percent: int | None


class AtsCheckItem(BaseModel):
    key: str
    label: str
    status: CheckStatusValue
    detail: str


class AtsSummary(BaseModel):
    passed: int
    warn: int
    fail: int


class AtsCheckRead(BaseModel):
    # Which resume was checked: your tailored draft with accepted changes, or the one built from
    # your profile.
    resume_source: ResumeSource
    accepted_changes: int
    keyword_stats: AtsKeywordStats
    keywords: list[AtsKeywordRead]
    checks: list[AtsCheckItem]
    summary: AtsSummary
    limitations: list[str] = LIMITATIONS


class AtsSafeExport(BaseModel):
    filename: str
    text: str
    resume_source: ResumeSource
    accepted_changes: int
