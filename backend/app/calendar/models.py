import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# connected: token works. needs_reauth: the refresh token was rejected or has expired — the
# user must reconnect. disconnected: the user disconnected; tokens are cleared.
CONNECTION_STATUSES = ("connected", "needs_reauth", "disconnected")


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

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
