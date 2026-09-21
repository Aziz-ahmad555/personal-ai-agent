import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from app.profile.schemas import SkillLevel

ConnectionStatus = Literal["connected", "needs_reauth", "disconnected"]


class ConnectionRead(BaseModel):
    """Deliberately has no token fields: nothing an API client can ask for returns a credential."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    github_login: str
    status: ConnectionStatus
    installations: list[dict[str, Any]]
    last_error: str | None
    created_at: datetime


class DisconnectResult(BaseModel):
    connection: ConnectionRead
    # Whether GitHub confirmed the token was revoked. False means it was only cleared locally
    # (GitHub was unreachable or refused); it will still expire on its own.
    revoked_at_github: bool


class RepoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    full_name: str
    html_url: str
    description: str | None
    is_fork: bool
    is_archived: bool
    primary_language: str | None
    topics: list[str]
    stars: int
    forks: int
    license_spdx: str | None
    pushed_at: datetime | None
    details_fetched: bool
    languages: dict[str, int]
    # None means "not looked up", which is different from 0.
    authored_commits: int | None
    first_commit_at: datetime | None
    last_commit_at: datetime | None
    dependencies: list[dict[str, Any]]
    synced_at: datetime


class SyncRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: Literal["pending", "running", "completed", "failed"]
    started_at: datetime
    completed_at: datetime | None
    repos_seen: int
    repos_detailed: int
    requests_made: int
    activity: dict[str, Any] | None
    warnings: list[str]
    skipped: list[dict[str, str]]
    error: str | None


class ContributionRead(BaseModel):
    repo: str
    repo_url: str
    via: Literal["language", "dependency", "file"]
    source_url: str
    source_file: str | None
    bytes: int | None
    commits: int | None
    last_commit_at: str | None
    attribution: Literal["attributed", "ownership_only", "unknown"]


class ProposalRead(BaseModel):
    id: uuid.UUID
    skill_name: str
    kind: Literal["language", "framework", "tool"]
    attribution: Literal["attributed", "ownership_only", "unknown"]
    contributions: list[ContributionRead]
    existing_skill_name: str | None
    existing_level: str | None
    # A new skill (or one with no level yet) needs the user to choose one before accepting.
    requires_level: bool
    # Exactly the evidence text that will be saved on the skill if this is accepted.
    evidence_preview: str
    status: Literal["pending", "accepted", "dismissed"]
    decided_at: datetime | None
    created_at: datetime


class AcceptRequest(BaseModel):
    level: SkillLevel | None = None


class AcceptResult(BaseModel):
    proposal: ProposalRead
    skill_id: uuid.UUID
    skill_version_id: uuid.UUID
