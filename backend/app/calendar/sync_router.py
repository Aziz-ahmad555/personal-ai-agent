import uuid
from typing import Annotated

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import log_action
from app.auth.deps import get_current_user
from app.calendar import sync as sync_service
from app.calendar.models import CalendarConnection, CalendarEvent, CalendarSyncRun
from app.calendar.schemas import (
    CalendarEventRead,
    ClassifyEventRequest,
    EventAttendee,
    LinkedApplication,
    SyncRunRead,
)
from app.career.models import Application, JobPosting
from app.core.demo import require_not_demo_mode
from app.db import base as db_base
from app.db.base import get_db
from app.db.models import User

router = APIRouter(prefix="/calendar", tags=["calendar"])

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


async def _connection(db: AsyncSession, user: User) -> CalendarConnection:
    connection = (
        await db.execute(select(CalendarConnection).where(CalendarConnection.user_id == user.id))
    ).scalar_one_or_none()
    if connection is None:
        raise _NOT_FOUND
    return connection


def _run_read(run: CalendarSyncRun) -> SyncRunRead:
    read = SyncRunRead.model_validate(run)
    if sync_service.is_stalled(run):
        # An orphaned run is reported as failed so the UI stops polling and offers a retry.
        read.status = "failed"
        read.error = sync_service.STALLED_MESSAGE
    return read


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
            detail="Calendar isn't connected — connect or reconnect it first.",
        )
    recent = (
        (
            await db.execute(
                select(CalendarSyncRun)
                .where(CalendarSyncRun.connection_id == connection.id)
                .order_by(CalendarSyncRun.started_at.desc())
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
                select(CalendarSyncRun)
                .where(CalendarSyncRun.connection_id == connection.id)
                .order_by(CalendarSyncRun.started_at.desc())
                .limit(10)
            )
        )
        .scalars()
        .all()
    )
    return [_run_read(run) for run in runs]


async def _event_read(db: AsyncSession, event: CalendarEvent) -> CalendarEventRead:
    application = None
    if event.application_id:
        row = (
            await db.execute(
                select(Application.id, JobPosting.id, JobPosting.title, JobPosting.company_name)
                .join(JobPosting, Application.job_posting_id == JobPosting.id)
                .where(Application.id == event.application_id)
            )
        ).first()
        if row:
            application = LinkedApplication(
                id=row[0], job_posting_id=row[1], title=row[2], company_name=row[3]
            )
    return CalendarEventRead(
        id=event.id,
        html_link=event.html_link,
        summary=event.summary,
        description=event.description,
        location=event.location,
        start_at=event.start_at,
        end_at=event.end_at,
        is_all_day=event.is_all_day,
        organizer_email=event.organizer_email,
        attendees=[EventAttendee(**a) for a in event.attendees],
        kind=event.kind,
        match_reason=event.match_reason,
        user_confirmed=event.user_confirmed,
        application=application,
        application_match_reason=event.application_match_reason,
    )


@router.get("/events", response_model=list[CalendarEventRead])
async def list_events(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[CalendarEventRead]:
    connection = await _connection(db, current_user)
    events = (
        (
            await db.execute(
                select(CalendarEvent)
                .where(CalendarEvent.connection_id == connection.id)
                .order_by(CalendarEvent.start_at.asc().nulls_last())
            )
        )
        .scalars()
        .all()
    )
    return [await _event_read(db, event) for event in events]


async def _owned_event(
    db: AsyncSession, connection: CalendarConnection, event_id: uuid.UUID
) -> CalendarEvent:
    event = (
        await db.execute(
            select(CalendarEvent).where(
                CalendarEvent.id == event_id, CalendarEvent.connection_id == connection.id
            )
        )
    ).scalar_one_or_none()
    if event is None:
        raise _NOT_FOUND
    return event


@router.post("/events/{event_id}/classify", response_model=CalendarEventRead)
async def classify_event(
    event_id: uuid.UUID,
    payload: ClassifyEventRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CalendarEventRead:
    """A user correction to this app's own read of one event — never sent anywhere, and
    never overwritten by a later sync (see sync.py). Green: a label on the user's own local
    data, with no external effect."""
    connection = await _connection(db, current_user)
    event = await _owned_event(db, connection, event_id)

    if payload.application_id is not None:
        owned = (
            await db.execute(
                select(Application.id).where(
                    Application.id == payload.application_id, Application.user_id == current_user.id
                )
            )
        ).scalar_one_or_none()
        if owned is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="No such tracked application."
            )

    previous_kind = event.kind
    event.kind = payload.kind
    event.match_reason = None
    event.user_confirmed = True
    event.application_id = payload.application_id
    event.application_match_reason = "Linked by you" if payload.application_id else None
    await log_action(
        db,
        user_id=current_user.id,
        action="calendar.event.classified",
        risk_level="green",
        summary=f"Set a calendar event's type to {payload.kind}.",
        evidence={
            "event_id": str(event.id),
            "previous_kind": previous_kind,
            "kind": payload.kind,
            "application_id": str(payload.application_id) if payload.application_id else None,
        },
        resource_type="calendar_event",
        resource_id=event.id,
    )
    await db.commit()
    await db.refresh(event)
    return await _event_read(db, event)
