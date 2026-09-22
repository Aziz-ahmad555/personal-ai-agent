import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

ConnectionStatus = Literal["connected", "needs_reauth", "disconnected"]
SyncStatus = Literal["pending", "running", "completed", "failed"]
EventKind = Literal["interview", "deadline", "other"]


class ConnectionRead(BaseModel):
    """Deliberately has no token fields: nothing an API client can ask for returns a credential."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    google_email: str
    status: ConnectionStatus
    last_error: str | None
    created_at: datetime


class DisconnectResult(BaseModel):
    connection: ConnectionRead
    # Whether Google confirmed the token was revoked. False means it was only cleared locally
    # (Google was unreachable or refused); it will still expire on its own.
    revoked_at_google: bool


class SyncRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: SyncStatus
    started_at: datetime
    completed_at: datetime | None
    events_seen: int
    events_stored: int
    warnings: list[str]
    error: str | None


class EventAttendee(BaseModel):
    email: str | None
    display_name: str | None
    response_status: str | None


class LinkedApplication(BaseModel):
    id: uuid.UUID
    title: str | None
    company_name: str | None


class CalendarEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    html_link: str | None
    summary: str | None
    description: str | None
    location: str | None
    start_at: datetime | None
    end_at: datetime | None
    is_all_day: bool
    organizer_email: str | None
    attendees: list[EventAttendee]
    kind: EventKind
    match_reason: str | None
    user_confirmed: bool
    application: LinkedApplication | None
    application_match_reason: str | None


class ClassifyEventRequest(BaseModel):
    kind: EventKind
    application_id: uuid.UUID | None = None
