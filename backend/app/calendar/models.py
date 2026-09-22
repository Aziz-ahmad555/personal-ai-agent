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

# connected: token works. needs_reauth: the refresh token was rejected or has expired — the
# user must reconnect. disconnected: the user disconnected; tokens are cleared.
CONNECTION_STATUSES = ("connected", "needs_reauth", "disconnected")
SYNC_STATUSES = ("pending", "running", "completed", "failed")
EVENT_KINDS = ("interview", "deadline", "other")


class CalendarConnection(Base):
    """One per user. Same Google Cloud project and OAuth client as Gmail, but its own
    connection: a separate grant (calendar.events.readonly only), a separate callback, and
    independent connect/disconnect, so this integration's CAN/CANNOT list stays its own and
    revoking one Google integration never silently affects the other."""

    __tablename__ = "calendar_connections"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    google_email: Mapped[str] = mapped_column(String(255), nullable=False)

    # Fernet-encrypted at the application layer (see app/gmail/crypto.py, reused as-is —
    # it's already generic over which integration's tokens it protects). Never plaintext.
    access_token_encrypted: Mapped[str | None] = mapped_column(Text)
    refresh_token_encrypted: Mapped[str | None] = mapped_column(Text)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Space-separated, exactly what Google returned — never assumed to match what was requested.
    granted_scopes: Mapped[str] = mapped_column(String(500), nullable=False)

    status: Mapped[str] = mapped_column(String(20), default="connected", nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)

    # Calendar API sync cursor (see app/calendar/sync.py). None means "never completed a full
    # sync yet" — the sync pipeline uses that to decide a full window list vs. incremental.
    sync_token: Mapped[str | None] = mapped_column(Text)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class CalendarEvent(Base):
    """A read-only mirror of one event on the user's primary calendar, plus this app's own
    deterministic classification. Cancelled events are removed on sync, not stored."""

    __tablename__ = "calendar_events"
    __table_args__ = (
        UniqueConstraint("connection_id", "google_event_id", name="uq_calendar_event"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("calendar_connections.id", ondelete="CASCADE"), index=True, nullable=False
    )
    google_event_id: Mapped[str] = mapped_column(String(200), nullable=False)
    html_link: Mapped[str | None] = mapped_column(String(500))

    summary: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(Text)
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_all_day: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    organizer_email: Mapped[str | None] = mapped_column(String(255))
    attendees: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)

    # This app's own read of the event — never Google's data, always ours, always revisable.
    # kind/match_reason are the automatic classification; a user override replaces both and
    # sets user_confirmed, so a later sync's re-classification never overwrites their choice.
    kind: Mapped[str] = mapped_column(String(20), default="other", nullable=False)
    match_reason: Mapped[str | None] = mapped_column(Text)
    user_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    application_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("applications.id", ondelete="SET NULL")
    )
    application_match_reason: Mapped[str | None] = mapped_column(Text)

    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CalendarSyncRun(Base):
    __tablename__ = "calendar_sync_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("calendar_connections.id", ondelete="CASCADE"), index=True, nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    events_seen: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    events_stored: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
