import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
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
PROPOSAL_STATUSES = ("pending", "accepted", "dismissed")


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

    # The public profile fields (name, bio, location, website, ...) from the last sync. None
    # means a sync from before these were recorded.
    profile_facts: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    status: Mapped[str] = mapped_column(String(20), default="connected", nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class GithubRepo(Base):
    """A snapshot of one of the user's own public repositories, refreshed on each sync."""

    __tablename__ = "github_repos"
    __table_args__ = (UniqueConstraint("connection_id", "github_repo_id", name="uq_github_repo"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("github_connections.id", ondelete="CASCADE"), index=True, nullable=False
    )
    github_repo_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    full_name: Mapped[str] = mapped_column(String(300), nullable=False)
    html_url: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_fork: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    primary_language: Mapped[str | None] = mapped_column(String(100))
    topics: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    stars: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    forks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    license_spdx: Mapped[str | None] = mapped_column(String(100))
    homepage: Mapped[str | None] = mapped_column(String(500))
    default_branch: Mapped[str | None] = mapped_column(String(200))
    created_at_gh: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pushed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Filled by the detail pass (skipped for forks and archived repos, which aren't evidence).
    details_fetched: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    languages: Mapped[dict[str, int]] = mapped_column(JSON, default=dict, nullable=False)
    # File and folder names in the repo root, kept so the readiness review can use them later.
    root_files: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    dependencies: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    # For the readiness review. None means "never collected" (a sync from before these existed),
    # which the review reports as unknown rather than as missing.
    tree_truncated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notable_paths: Mapped[dict[str, list[str]] | None] = mapped_column(JSON)
    # README structure only (word count, headings, code blocks, images), never its text.
    readme: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    # Commits GitHub attributes to the connected account. None: not looked up (different from 0).
    authored_commits: Mapped[int | None] = mapped_column(Integer)
    first_commit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_commit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class GithubSyncRun(Base):
    __tablename__ = "github_sync_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("github_connections.id", ondelete="CASCADE"), index=True, nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    repos_seen: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    repos_detailed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    requests_made: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    activity: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    # Things that couldn't be fetched, and things left out of proposals, each with the reason.
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    skipped: Mapped[list[dict[str, str]]] = mapped_column(JSON, default=list, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)


class GithubSkillProposal(Base):
    """A skill the user's repos evidence, waiting for their decision. One row per (skill, the
    evidence it stands on): new evidence makes a new row, while a decision on old evidence stays
    as history and is never silently re-asked."""

    __tablename__ = "github_skill_proposals"
    __table_args__ = (
        UniqueConstraint("connection_id", "skill_name", "fingerprint", name="uq_github_proposal"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("github_connections.id", ondelete="CASCADE"), index=True, nullable=False
    )
    skill_name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    contributions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    attribution: Mapped[str] = mapped_column(String(20), nullable=False)
    existing_skill_name: Mapped[str | None] = mapped_column(String(120))
    existing_level: Mapped[str | None] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    skill_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("skill_versions.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
