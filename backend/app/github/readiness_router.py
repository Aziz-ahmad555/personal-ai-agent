"""The recruiter-readiness review, computed on demand from the stored snapshot. It reads only
local data, so it costs no GitHub requests and can't drift from what the last sync saw."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import log_action
from app.auth.deps import get_current_user
from app.db.base import get_db
from app.db.models import User
from app.github import readiness as r
from app.github.models import GithubConnection, GithubRepo, GithubSyncRun
from app.github.schemas import (
    CheckRead,
    FixRead,
    ReadinessExport,
    ReadinessRead,
    RepoReviewRead,
)

router = APIRouter(prefix="/github", tags=["github"])

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


@dataclass
class _Review:
    login: str
    as_of: datetime | None
    synced: bool
    needs_resync: bool
    repos: list[r.RepoReview]
    profile: list[r.Check]
    fixes: list[r.Fix]


def _facts(row: GithubRepo) -> r.ReviewFacts:
    return r.ReviewFacts(
        name=row.name,
        html_url=row.html_url,
        default_branch=row.default_branch,
        description=row.description,
        license_spdx=row.license_spdx,
        topics=list(row.topics or []),
        pushed_at=row.pushed_at,
        is_fork=row.is_fork,
        is_archived=row.is_archived,
        details_fetched=row.details_fetched,
        root_files=list(row.root_files or []),
        tree_truncated=row.tree_truncated,
        notable=row.notable_paths,
        readme=row.readme,
    )


async def _review(db: AsyncSession, user: User) -> _Review:
    connection = (
        await db.execute(select(GithubConnection).where(GithubConnection.user_id == user.id))
    ).scalar_one_or_none()
    if connection is None:
        raise _NOT_FOUND
    rows = (
        (
            await db.execute(
                select(GithubRepo)
                .where(GithubRepo.connection_id == connection.id)
                .order_by(GithubRepo.pushed_at.desc().nulls_last(), GithubRepo.name)
            )
        )
        .scalars()
        .all()
    )
    last_done = (
        await db.execute(
            select(GithubSyncRun)
            .where(
                GithubSyncRun.connection_id == connection.id, GithubSyncRun.status == "completed"
            )
            .order_by(GithubSyncRun.started_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    reviews = [r.review_repo(_facts(row)) for row in rows]
    # Nothing has been synced, so there is nothing to judge: no checks and no fixes, rather than
    # an account that "fails" because it hasn't been read yet.
    profile = (
        r.review_profile(
            connection.profile_facts, connection.github_login, reviews, [row.name for row in rows]
        )
        if last_done is not None
        else []
    )
    fixes = r.top_fixes(reviews, profile)
    # "Unknown only because the last sync is older than these checks" is worth saying out loud.
    needs_resync = last_done is not None and any(
        c.status == "unknown" and c.detail == r.RESYNC
        for c in [*profile, *(c for rev in reviews for c in rev.checks)]
    )
    as_of = last_done.completed_at if last_done else None
    if as_of is not None and as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=UTC)
    return _Review(
        connection.github_login, as_of, last_done is not None, needs_resync, reviews, profile, fixes
    )


def _check(c: r.Check) -> CheckRead:
    return CheckRead(
        key=c.key,
        label=c.label,
        status=c.status,
        detail=c.detail,
        evidence_url=c.evidence_url,
        fix=c.fix,
    )


@router.get("/readiness", response_model=ReadinessRead)
async def get_readiness(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ReadinessRead:
    review = await _review(db, current_user)
    return ReadinessRead(
        synced=review.synced,
        as_of=review.as_of,
        needs_resync=review.needs_resync,
        repos=[
            RepoReviewRead(
                name=rev.name,
                html_url=rev.html_url,
                reviewed=rev.reviewed,
                reason=rev.reason,
                checks=[_check(c) for c in rev.checks],
                passed=rev.passed,
                total=len(rev.checks),
                unknown=rev.unknown,
            )
            for rev in review.repos
        ],
        profile=[_check(c) for c in review.profile],
        fixes=[
            FixRead(
                repo=f.repo,
                repo_url=f.repo_url,
                check_key=f.check_key,
                label=f.label,
                status=f.status,
                detail=f.detail,
                fix=f.fix,
                evidence_url=f.evidence_url,
            )
            for f in review.fixes
        ],
        limitations=list(r.LIMITATIONS),
    )


@router.get("/readiness/export", response_model=ReadinessExport)
async def export_readiness(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ReadinessExport:
    """The review as a Markdown checklist. Nothing leaves the app: the text is returned for the
    user to copy, and the export is recorded."""
    review = await _review(db, current_user)
    text = r.export_markdown(review.login, review.as_of, review.repos, review.profile, review.fixes)
    await log_action(
        db,
        user_id=current_user.id,
        action="github.readiness.exported",
        risk_level="green",
        summary="Exported the GitHub readiness checklist.",
        evidence={
            "repos_reviewed": sum(rev.reviewed for rev in review.repos),
            "fixes": len(review.fixes),
        },
    )
    await db.commit()
    return ReadinessExport(filename=f"github-readiness-{review.login}.md", text=text)
