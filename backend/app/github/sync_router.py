import uuid
from typing import Annotated

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.core.demo import require_not_demo_mode
from app.db import base as db_base
from app.db.base import get_db
from app.db.models import User
from app.github import proposals as proposal_service
from app.github import sync as sync_service
from app.github.models import GithubConnection, GithubRepo, GithubSkillProposal, GithubSyncRun
from app.github.schemas import (
    AcceptRequest,
    AcceptResult,
    ContributionRead,
    ProposalRead,
    RepoRead,
    SyncRunRead,
)

router = APIRouter(prefix="/github", tags=["github"])

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


async def _connection(db: AsyncSession, user: User) -> GithubConnection:
    connection = (
        await db.execute(select(GithubConnection).where(GithubConnection.user_id == user.id))
    ).scalar_one_or_none()
    if connection is None:
        raise _NOT_FOUND
    return connection


def _run_read(run: GithubSyncRun) -> SyncRunRead:
    read = SyncRunRead.model_validate(run)
    if sync_service.is_stalled(run):
        # An orphaned run is reported as failed so the UI stops polling and offers a retry.
        read.status = "failed"
        read.error = sync_service.STALLED_MESSAGE
    return read


def _proposal_read(connection: GithubConnection, row: GithubSkillProposal) -> ProposalRead:
    return ProposalRead(
        id=row.id,
        skill_name=row.skill_name,
        kind=row.kind,
        attribution=row.attribution,
        contributions=[ContributionRead(**c) for c in row.contributions],
        existing_skill_name=row.existing_skill_name,
        existing_level=row.existing_level,
        requires_level=row.existing_level is None,
        evidence_preview=proposal_service.preview_evidence(connection, row),
        status=row.status,
        decided_at=row.decided_at,
        created_at=row.created_at,
    )


async def _run_in_background(run_id: uuid.UUID) -> None:
    structlog.contextvars.bind_contextvars(task_id=str(run_id))
    async with db_base.async_session_factory() as db:
        await sync_service.run_sync(db, run_id)


@router.post(
    "/sync",
    response_model=SyncRunRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_not_demo_mode)],
)
async def start_sync(
    background_tasks: BackgroundTasks,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SyncRunRead:
    connection = await _connection(db, current_user)
    if connection.status != "connected":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="GitHub isn't connected — connect or reconnect it first.",
        )
    recent = (
        (
            await db.execute(
                select(GithubSyncRun)
                .where(GithubSyncRun.connection_id == connection.id)
                .order_by(GithubSyncRun.started_at.desc())
                .limit(5)
            )
        )
        .scalars()
        .all()
    )
    if any(sync_service.is_active(run) for run in recent):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="A sync is already running."
        )
    run = await sync_service.start_run(db, connection.id)
    background_tasks.add_task(_run_in_background, run.id)
    return _run_read(run)


@router.get("/sync", response_model=list[SyncRunRead])
async def list_sync_runs(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[SyncRunRead]:
    connection = await _connection(db, current_user)
    runs = (
        (
            await db.execute(
                select(GithubSyncRun)
                .where(GithubSyncRun.connection_id == connection.id)
                .order_by(GithubSyncRun.started_at.desc())
                .limit(10)
            )
        )
        .scalars()
        .all()
    )
    return [_run_read(run) for run in runs]


@router.get("/repos", response_model=list[RepoRead])
async def list_repos(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[GithubRepo]:
    connection = await _connection(db, current_user)
    return list(
        (
            await db.execute(
                select(GithubRepo)
                .where(GithubRepo.connection_id == connection.id)
                .order_by(GithubRepo.pushed_at.desc().nulls_last(), GithubRepo.name)
            )
        ).scalars()
    )


@router.get("/proposals", response_model=list[ProposalRead])
async def list_proposals(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[ProposalRead]:
    connection = await _connection(db, current_user)
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
    order = {"pending": 0, "accepted": 1, "dismissed": 2}
    attribution = {"attributed": 0, "unknown": 1, "ownership_only": 2}
    rows = sorted(
        rows,
        key=lambda r: (
            order[r.status],
            attribution[r.attribution],
            -sum(c.get("commits") or 0 for c in r.contributions),
            r.skill_name.lower(),
        ),
    )
    return [_proposal_read(connection, row) for row in rows]


async def _owned_proposal(
    db: AsyncSession, connection: GithubConnection, proposal_id: uuid.UUID
) -> GithubSkillProposal:
    row = (
        await db.execute(
            select(GithubSkillProposal).where(
                GithubSkillProposal.id == proposal_id,
                GithubSkillProposal.connection_id == connection.id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise _NOT_FOUND
    return row


@router.post("/proposals/{proposal_id}/accept", response_model=AcceptResult)
async def accept_proposal(
    proposal_id: uuid.UUID,
    payload: AcceptRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AcceptResult:
    connection = await _connection(db, current_user)
    row = await _owned_proposal(db, connection, proposal_id)
    try:
        skill, version = await proposal_service.accept_proposal(db, connection, row, payload.level)
    except proposal_service.ProposalStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except proposal_service.LevelRequiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    await db.refresh(row)
    return AcceptResult(
        proposal=_proposal_read(connection, row), skill_id=skill.id, skill_version_id=version.id
    )


@router.post("/proposals/{proposal_id}/dismiss", response_model=ProposalRead)
async def dismiss_proposal(
    proposal_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ProposalRead:
    connection = await _connection(db, current_user)
    row = await _owned_proposal(db, connection, proposal_id)
    try:
        await proposal_service.dismiss_proposal(db, connection, row)
    except proposal_service.ProposalStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await db.refresh(row)
    return _proposal_read(connection, row)
