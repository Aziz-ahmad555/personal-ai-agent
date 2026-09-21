"""Reads the user's own public repositories into a local snapshot and works out which skills
they evidence. Read-only against GitHub, and it never touches the profile: the result is a list
of proposals the user accepts or dismisses (see proposals.py)."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.audit.service import log_action
from app.career.matching import normalize_skill
from app.github import client as gh
from app.github import readiness
from app.github.catalog import dependency_skills, is_manifest
from app.github.derive import (
    DependencyFact,
    ExistingSkill,
    RepoFacts,
    contribution_to_dict,
    derive,
    summarize_events,
)
from app.github.models import GithubConnection, GithubRepo, GithubSkillProposal, GithubSyncRun
from app.github.service import NotConnectedError, get_valid_access_token
from app.logging import get_logger
from app.profile.models import Profile, Skill

logger = get_logger(__name__)

# A sync makes a few requests per repo. Past this many, it stops and says which repos it missed.
MAX_REQUESTS = 300
MAX_MANIFESTS_PER_REPO = 5

# The background task lives inside the server process, so a restart silently kills it. A run
# still "running" long after it started is reported as failed, detected on read.
SYNC_TIMEOUT = timedelta(minutes=10)
STALLED_MESSAGE = (
    "This sync didn't finish — the server was probably restarted while it was running. Try again."
)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def is_active(run: GithubSyncRun, *, now: datetime | None = None) -> bool:
    """Pending or running, and not yet old enough to be presumed dead."""
    if run.status not in ("pending", "running"):
        return False
    return (now or datetime.now(UTC)) - _aware(run.started_at) <= SYNC_TIMEOUT


def is_stalled(run: GithubSyncRun, *, now: datetime | None = None) -> bool:
    if run.status not in ("pending", "running"):
        return False
    return (now or datetime.now(UTC)) - _aware(run.started_at) > SYNC_TIMEOUT


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return _aware(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return None


def _iso(value: datetime | None) -> str | None:
    return _aware(value).isoformat() if value else None


def repo_facts(row: GithubRepo) -> RepoFacts:
    return RepoFacts(
        name=row.name,
        full_name=row.full_name,
        html_url=row.html_url,
        is_fork=row.is_fork,
        is_archived=row.is_archived,
        languages=dict(row.languages or {}),
        authored_commits=row.authored_commits,
        last_commit_at=_iso(row.last_commit_at),
        root_files=list(row.root_files or []),
        dependencies=[DependencyFact(**d) for d in row.dependencies or []],
        details_fetched=row.details_fetched,
    )


async def existing_skills(db: AsyncSession, user_id: uuid.UUID) -> dict[str, ExistingSkill]:
    """The user's current profile skills, keyed by normalized name, with their latest level."""
    profile = (
        await db.execute(select(Profile).where(Profile.user_id == user_id))
    ).scalar_one_or_none()
    if profile is None:
        return {}
    skills = (
        (
            await db.execute(
                select(Skill)
                .where(Skill.profile_id == profile.id)
                .options(selectinload(Skill.versions))
            )
        )
        .scalars()
        .all()
    )
    return {
        normalize_skill(skill.name): ExistingSkill(
            skill.name, skill.versions[0].level if skill.versions else None
        )
        for skill in skills
    }


async def start_run(db: AsyncSession, connection_id: uuid.UUID) -> GithubSyncRun:
    run = GithubSyncRun(connection_id=connection_id, status="pending")
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return run


async def run_sync(db: AsyncSession, run_id: uuid.UUID) -> None:
    run = await db.get(GithubSyncRun, run_id)
    if run is None:
        logger.warning("github_sync_run_not_found", run_id=str(run_id))
        return
    # Plain values, read once: after any failed flush the session rolls back and expires every
    # object, so the failure path must not depend on touching them.
    connection_id = run.connection_id
    connection = await db.get(GithubConnection, connection_id)
    if connection is None:
        await _fail(db, run_id, "The GitHub connection no longer exists.")
        return

    run.status = "running"
    run.started_at = datetime.now(UTC)
    await db.commit()

    try:
        token = await get_valid_access_token(db, connection)
    except Exception as exc:  # noqa: BLE001 — every failure is reported on the run
        await _fail(db, run_id, _describe(exc))
        return

    http: gh.GithubHttp | None = None
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            http = gh.GithubHttp(client, token, budget=MAX_REQUESTS)
            await _sync(db, run, connection, http)
    except gh.GithubAuthError:
        await _fail(
            db,
            run_id,
            "GitHub rejected the access token — reconnect GitHub.",
            http,
            needs_reauth=True,
        )
    except Exception as exc:  # noqa: BLE001 — a background task must record, not raise
        logger.warning("github_sync_failed", error=str(exc))
        await _fail(db, run_id, _describe(exc), http)


def _describe(exc: Exception) -> str:
    if isinstance(exc, gh.GithubApiError | NotConnectedError):
        return str(exc)
    return "Something went wrong while syncing. Try again."


async def _fail(
    db: AsyncSession,
    run_id: uuid.UUID,
    message: str,
    http: gh.GithubHttp | None = None,
    *,
    needs_reauth: bool = False,
) -> None:
    await db.rollback()  # drop any half-finished work, then record the failure cleanly
    run = await db.get(GithubSyncRun, run_id)
    if run is None:
        return
    run.status = "failed"
    run.error = message
    run.completed_at = datetime.now(UTC)
    if http is not None:
        run.requests_made = http.requests_made
    connection = await db.get(GithubConnection, run.connection_id)
    if connection is not None:
        if needs_reauth:
            connection.status = "needs_reauth"
            connection.last_error = "GitHub rejected the access token."
        await log_action(
            db,
            user_id=connection.user_id,
            action="github.sync_failed",
            risk_level="green",
            summary="GitHub sync did not complete.",
            error=message,
            resource_type="github_sync_run",
            resource_id=run.id,
        )
    await db.commit()


async def _sync(
    db: AsyncSession, run: GithubSyncRun, connection: GithubConnection, http: gh.GithubHttp
) -> None:
    warnings: list[str] = []

    # The token proves which account this is. If the user renamed it, follow the rename.
    account = (await http.get("/user")).json()
    if not isinstance(account, dict) or not isinstance(account.get("login"), str):
        raise gh.GithubApiError("GitHub's user response was missing a login.")
    if account["login"] != connection.github_login:
        connection.github_login = account["login"]
    # Public profile fields for the readiness review (already in this response: no extra request).
    connection.profile_facts = {key: account.get(key) for key in PROFILE_FIELDS}
    login = connection.github_login

    listed = await gh.list_owned_public_repos(http, login)
    run.repos_seen = len(listed)
    rows = await _upsert_repos(db, connection, listed)
    await db.commit()

    detailed = 0
    for row in rows:
        if row.is_fork or row.is_archived:
            continue
        try:
            warnings.extend(await _fetch_details(http, row, login))
            detailed += 1
            await db.commit()
        except (gh.RateLimitedError, gh.RequestBudgetExceededError) as exc:
            await db.rollback()
            warnings.append(f"Stopped early: {exc} Repos not yet read keep their previous data.")
            break
        except gh.GithubAuthError:
            raise
        except gh.GithubApiError as exc:
            await db.rollback()
            warnings.append(f"{row.name}: couldn't be read this time ({exc}).")

    activity: dict[str, Any] | None = None
    try:
        activity = summarize_events(await gh.list_public_events(http, login))
    except (gh.RateLimitedError, gh.RequestBudgetExceededError, gh.GithubApiError) as exc:
        warnings.append(f"Recent activity couldn't be read ({exc}).")

    refreshed = (
        (await db.execute(select(GithubRepo).where(GithubRepo.connection_id == connection.id)))
        .scalars()
        .all()
    )
    existing = await existing_skills(db, connection.user_id)
    derivation = derive([repo_facts(r) for r in refreshed], existing)
    await _store_proposals(db, connection, derivation.proposals)

    run.repos_detailed = detailed
    run.requests_made = http.requests_made
    run.activity = activity
    run.warnings = warnings
    run.skipped = [{"subject": s.subject, "reason": s.reason} for s in derivation.skipped]
    run.status = "completed"
    run.completed_at = datetime.now(UTC)
    await log_action(
        db,
        user_id=connection.user_id,
        action="github.synced",
        risk_level="green",
        summary=(
            f"Synced {len(listed)} public repositories from GitHub ({detailed} read in detail)."
        ),
        evidence={
            "repos_seen": len(listed),
            "repos_detailed": detailed,
            "requests_made": http.requests_made,
            "proposals": len(derivation.proposals),
            "warnings": warnings,
        },
        resource_type="github_sync_run",
        resource_id=run.id,
    )
    await db.commit()


async def _upsert_repos(
    db: AsyncSession, connection: GithubConnection, listed: list[dict[str, Any]]
) -> list[GithubRepo]:
    current = {
        row.github_repo_id: row
        for row in (
            await db.execute(select(GithubRepo).where(GithubRepo.connection_id == connection.id))
        )
        .scalars()
        .all()
    }
    seen: set[int] = set()
    rows: list[GithubRepo] = []
    for item in listed:
        seen.add(item["id"])
        row = current.get(item["id"])
        if row is None:
            row = GithubRepo(connection_id=connection.id, github_repo_id=item["id"])
            db.add(row)
        row.name = item["name"]
        row.full_name = item["full_name"]
        row.html_url = item["html_url"]
        row.description = item["description"]
        row.is_fork = item["fork"]
        row.is_archived = item["archived"]
        row.primary_language = item["language"]
        row.topics = list(item["topics"])
        row.stars = item["stars"]
        row.forks = item["forks"]
        row.license_spdx = item["license_spdx"]
        row.homepage = item["homepage"]
        row.default_branch = item["default_branch"]
        row.created_at_gh = _parse_dt(item["created_at"])
        row.pushed_at = _parse_dt(item["pushed_at"])
        row.synced_at = datetime.now(UTC)
        rows.append(row)
    stale = [rid for rid in current if rid not in seen]
    if stale:  # deleted or made private since the last sync
        await db.execute(
            delete(GithubRepo).where(
                GithubRepo.connection_id == connection.id, GithubRepo.github_repo_id.in_(stale)
            )
        )
    await db.flush()
    return rows


# Folders whose contents are dependencies or build output, never the user's own manifests.
IGNORED_DIRS = frozenset(
    {
        "node_modules",
        ".venv",
        "venv",
        "env",
        "site-packages",
        "dist",
        "build",
        "vendor",
        "third_party",
    }
)
MAX_MANIFEST_DEPTH = 2  # e.g. backend/requirements.txt or services/api/pyproject.toml


def manifest_paths(entries: list[gh.TreeEntry]) -> list[str]:
    """The dependency manifests worth reading, shallowest first. Vendored and generated folders
    are skipped so a committed node_modules can't pose as the user's dependencies."""
    found = []
    for entry in entries:
        if entry.type != "blob":
            continue
        parts = entry.path.split("/")
        if len(parts) - 1 > MAX_MANIFEST_DEPTH or not is_manifest(parts[-1]):
            continue
        if any(part in IGNORED_DIRS for part in parts[:-1]):
            continue
        found.append(entry.path)
    return sorted(found, key=lambda path: (path.count("/"), path))[:MAX_MANIFESTS_PER_REPO]


PROFILE_FIELDS = (
    "login",
    "name",
    "bio",
    "company",
    "location",
    "blog",
    "public_repos",
    "followers",
    "created_at",
    "hireable",
)


async def _read_readme(
    http: gh.GithubHttp, row: GithubRepo, root_names: list[str]
) -> dict[str, Any]:
    """The README's structure (never its text), or a note that there isn't one or it couldn't be
    read. Missing and unreadable are different answers and the review treats them differently."""
    path = readiness.readme_candidate(root_names)
    if path is None:
        return {"present": False}
    text = await gh.get_text_file(http, row.full_name, path)
    if text is None:
        return {
            "path": path,
            "present": True,
            "readable": False,
            "reason": "couldn't be read (it may be too large or not plain text).",
        }
    return readiness.readme_metrics(text, path)


async def _fetch_details(http: gh.GithubHttp, row: GithubRepo, login: str) -> list[str]:
    """All of a repo's detail or none of it: values are assigned only after every request worked,
    so a half-read repo never masquerades as a fully read one. Returns any warnings."""
    warnings: list[str] = []
    languages = await gh.get_languages(http, row.full_name)
    stats = await gh.get_commit_stats(http, row.full_name, login)
    ref = row.default_branch or "HEAD"
    entries, truncated = await gh.list_tree(http, row.full_name, ref)
    if truncated:
        warnings.append(
            f"{row.name}: GitHub cut off its file list (a very large repository), so some "
            "dependency files may be missed."
        )
    dependencies: list[dict[str, str]] = []
    for path in manifest_paths(entries):
        text = await gh.get_text_file(http, row.full_name, path)
        if not text:
            continue
        url = f"{row.html_url}/blob/{ref}/{path}"
        for skill in dependency_skills(path.rsplit("/", 1)[-1], text):
            dependencies.append({"skill": skill, "file": path, "url": url})

    root_names = [e.path for e in entries if "/" not in e.path]
    row.readme = await _read_readme(http, row, root_names)
    row.notable_paths = readiness.notable_paths([(e.path, e.type) for e in entries])
    row.tree_truncated = truncated

    row.languages = languages
    row.authored_commits = stats.count
    row.first_commit_at = _parse_dt(stats.first_at)
    row.last_commit_at = _parse_dt(stats.last_at)
    row.root_files = root_names
    row.dependencies = dependencies
    row.details_fetched = True
    return warnings


async def _store_proposals(
    db: AsyncSession, connection: GithubConnection, drafts: list[Any]
) -> None:
    rows = (
        (
            await db.execute(
                select(GithubSkillProposal).where(
                    GithubSkillProposal.connection_id == connection.id
                )
            )
        )
        .scalars()
        .all()
    )
    by_key = {(r.skill_name, r.fingerprint): r for r in rows}
    keep: set[tuple[str, str]] = set()
    for draft in drafts:
        key = (draft.skill_name, draft.fingerprint)
        keep.add(key)
        row = by_key.get(key)
        if row is None:
            row = GithubSkillProposal(
                connection_id=connection.id,
                skill_name=draft.skill_name,
                fingerprint=draft.fingerprint,
                status="pending",
            )
            db.add(row)
        # Counts and levels keep up with the repos even for decided proposals; the decision
        # itself (the status) is never touched.
        row.kind = draft.kind
        row.contributions = [contribution_to_dict(c) for c in draft.contributions]
        row.attribution = draft.attribution
        row.existing_skill_name = draft.existing_skill_name
        row.existing_level = draft.existing_level
    for row in rows:
        # Evidence that no longer stands (a repo went private, or was archived) withdraws an
        # undecided proposal. Decided ones stay as the record of what the user did.
        if row.status == "pending" and (row.skill_name, row.fingerprint) not in keep:
            await db.delete(row)
    await db.flush()
