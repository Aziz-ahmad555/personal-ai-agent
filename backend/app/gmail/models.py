import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

# connected: tokens valid, syncing works. needs_reauth: refresh failed (expired/revoked —
# expected every ~7 days while the Google OAuth consent screen stays in "Testing" status).
# disconnected: user explicitly disconnected; may or may not still have stored mail,
# depending on whether they chose to purge it.
CONNECTION_STATUSES = ("connected", "needs_reauth", "disconnected")

SYNC_RUN_STATUSES = ("pending", "running", "completed", "failed")
SYNC_TYPES = ("backfill", "incremental")


class GmailConnection(Base):
    """One per user (this is a single-user app, but modeled as a real relation rather
    than a singleton so ownership/cascade rules stay explicit and unsurprising)."""

    __tablename__ = "gmail_connections"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    google_email: Mapped[str] = mapped_column(String(255), nullable=False)

    # Fernet-encrypted at the application layer (see app/gmail/crypto.py) — never stored
    # or logged in plaintext. Nullable so a disconnected-without-purge row can have its
    # tokens cleared while keeping the connection record (and any retained mail) around.
    access_token_encrypted: Mapped[str | None] = mapped_column(Text)
    refresh_token_encrypted: Mapped[str | None] = mapped_column(Text)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Space-separated, exactly what Google returned — never assumed to match what was
    # requested.
    granted_scopes: Mapped[str] = mapped_column(String(500), nullable=False)

    status: Mapped[str] = mapped_column(String(20), default="connected", nullable=False)

    # Gmail History API cursor. None means "never completed a backfill yet" — the sync
    # pipeline uses that to decide backfill vs. incremental.
    last_history_id: Mapped[str | None] = mapped_column(String(50))

    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sync_error: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    messages: Mapped[list["EmailMessage"]] = relationship(
        back_populates="connection", cascade="all, delete-orphan"
    )
    sync_runs: Mapped[list["GmailSyncRun"]] = relationship(
        back_populates="connection", cascade="all, delete-orphan"
    )


class EmailMessage(Base):
    """A read-only mirror of a Gmail message: metadata + plain-text body only. No raw
    MIME, no attachments — nothing beyond what this stage actually needs, per
    data-minimization (see CLAUDE.md Phase 5 CAN/CANNOT)."""

    __tablename__ = "email_messages"
    __table_args__ = (
        UniqueConstraint("connection_id", "gmail_message_id", name="uq_email_gmail_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("gmail_connections.id", ondelete="CASCADE"), nullable=False
    )
    gmail_message_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    thread_id: Mapped[str] = mapped_column(String(50), nullable=False)

    subject: Mapped[str | None] = mapped_column(Text)
    from_address: Mapped[str | None] = mapped_column(String(500))
    to_addresses: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    snippet: Mapped[str] = mapped_column(Text, nullable=False, default="")
    body_text: Mapped[str | None] = mapped_column(Text)
    label_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)

    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    connection: Mapped[GmailConnection] = relationship(back_populates="messages")


class GmailSyncRun(Base):
    """One row per sync attempt — mirrors ResearchQuery's pending/running/completed/failed
    lifecycle so the frontend can poll it the same way."""

    __tablename__ = "gmail_sync_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("gmail_connections.id", ondelete="CASCADE"), nullable=False
    )
    sync_type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    messages_fetched: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    messages_stored: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    connection: Mapped[GmailConnection] = relationship(back_populates="sync_runs")
