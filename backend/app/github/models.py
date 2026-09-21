import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# connected: token works. needs_reauth: the refresh token was rejected or has expired — the
# user must reconnect. disconnected: the user disconnected; tokens are cleared.
CONNECTION_STATUSES = ("connected", "needs_reauth", "disconnected")


class GithubConnection(Base):
    """One per user. Holds the GitHub identity the user proved they own (by completing the
    OAuth handshake) and the encrypted tokens. Nothing here can write to GitHub: the GitHub
    App is registered without permissions, and the callback refuses one that has any."""

    __tablename__ = "github_connections"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    github_login: Mapped[str] = mapped_column(String(100), nullable=False)
    github_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Fernet-encrypted at the application layer (see app/gmail/crypto.py), never plaintext.
    access_token_encrypted: Mapped[str | None] = mapped_column(Text)
    refresh_token_encrypted: Mapped[str | None] = mapped_column(Text)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refresh_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # What GitHub reports about installations of the app the user can reach: account,
    # repository selection and permissions. Empty means the app isn't installed anywhere, so
    # only public data is reachable — which is all this integration uses.
    installations: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)

    status: Mapped[str] = mapped_column(String(20), default="connected", nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
