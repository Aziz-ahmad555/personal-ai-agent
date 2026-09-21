import uuid
from datetime import date, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.career.schemas import RemoteType

ApplicationStatus = Literal[
    "saved",
    "applied",
    "screening",
    "interviewing",
    "offer",
    "accepted",
    "rejected",
    "withdrawn",
    "no_response",
]
ApplicationEventType = Literal["status_change", "note", "interview"]
FollowUpState = Literal["overdue", "due_today", "upcoming"]


def _not_in_the_future(value: date | None) -> date | None:
    # One day of slack so a user west of the server's timezone isn't rejected for "today".
    if value is not None and value > date.today() + timedelta(days=1):
        raise ValueError("The date can't be in the future.")
    return value


class ApplicationCreate(BaseModel):
    job_posting_id: uuid.UUID
    notes: str | None = Field(default=None, max_length=4000)


class ApplicationStatusChange(BaseModel):
    status: ApplicationStatus
    # The date this actually happened; defaults to today. May be in the past (logging an
    # application days after sending it) but not the future.
    occurred_on: date | None = None
    note: str | None = Field(default=None, max_length=4000)

    _check_date = field_validator("occurred_on")(_not_in_the_future)


class ApplicationEventCreate(BaseModel):
    event_type: Literal["note", "interview"]
    occurred_on: date | None = None
    body: str = Field(min_length=1, max_length=4000)

    _check_date = field_validator("occurred_on")(_not_in_the_future)


class ApplicationUpdate(BaseModel):
    """PATCH semantics: only fields actually sent are changed, and an explicit null clears
    one (e.g. removing a follow-up) — see model_fields_set in the router."""

    notes: str | None = Field(default=None, max_length=4000)
    next_action_text: str | None = Field(default=None, max_length=255)
    next_action_on: date | None = None


class ApplicationJobSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str | None
    company_name: str | None
    location: str | None
    remote_type: RemoteType
    source_url: str | None


class ApplicationMatchSummary(BaseModel):
    """The posting's *current* match, for the board card. (The snapshot taken when the user
    applied lives on the timeline event, and doesn't change.)"""

    score_percent: int | None
    low_confidence: bool


class ApplicationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    job_posting_id: uuid.UUID
    status: ApplicationStatus
    notes: str | None
    applied_on: date | None
    next_action_text: str | None
    next_action_on: date | None
    follow_up_state: FollowUpState | None = None
    job: ApplicationJobSummary | None = None
    match: ApplicationMatchSummary | None = None
    # The server owns the rules; the UI just offers what these say is allowed.
    allowed_transitions: list[ApplicationStatus] = []
    reopen_targets: list[ApplicationStatus] = []
    created_at: datetime
    updated_at: datetime


class ApplicationEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_type: ApplicationEventType
    from_status: ApplicationStatus | None
    to_status: ApplicationStatus | None
    occurred_on: date
    body: str | None
    snapshot: dict[str, Any] | None
    created_at: datetime


class ApplicationDetail(ApplicationRead):
    events: list[ApplicationEventRead] = []
