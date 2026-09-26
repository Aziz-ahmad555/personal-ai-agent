import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import log_action
from app.auth.deps import get_current_user
from app.career import application_service
from app.career.application_rules import (
    ApplicationTransitionError,
    follow_up_state,
    forward_transitions,
    reopen_targets,
)
from app.career.application_schemas import (
    ApplicationCreate,
    ApplicationDetail,
    ApplicationEventCreate,
    ApplicationEventRead,
    ApplicationJobSummary,
    ApplicationMatchSummary,
    ApplicationRead,
    ApplicationStatus,
    ApplicationStatusChange,
    ApplicationUpdate,
)
from app.career.models import Application, ApplicationEvent, JobMatch, JobPosting
from app.db.base import get_db
from app.db.models import User

router = APIRouter(prefix="/career/applications", tags=["career"])

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


def _read_fields(
    application: Application, job: JobPosting | None, match: JobMatch | None
) -> dict[str, object]:
    """Everything ApplicationRead adds beyond the row itself. Rules and follow-up state are
    computed here (from app.career.application_rules) so the UI never re-implements them."""
    return {
        "follow_up_state": follow_up_state(
            application.next_action_on, application.status, today=datetime.now(UTC).date()
        ),
        "job": ApplicationJobSummary.model_validate(job) if job is not None else None,
        "match": (
            ApplicationMatchSummary(
                score_percent=match.score_percent, low_confidence=match.low_confidence
            )
            if match is not None and match.status == "completed"
            else None
        ),
        "allowed_transitions": forward_transitions(application.status),
        "reopen_targets": reopen_targets(application.status),
    }


async def _build_detail(db: AsyncSession, application: Application) -> ApplicationDetail:
    job = await db.get(JobPosting, application.job_posting_id)
    match = (
        await db.execute(
            select(JobMatch).where(JobMatch.job_posting_id == application.job_posting_id)
        )
    ).scalar_one_or_none()
    events = (
        (
            await db.execute(
                select(ApplicationEvent)
                .where(ApplicationEvent.application_id == application.id)
                .order_by(ApplicationEvent.occurred_on, ApplicationEvent.created_at)
            )
        )
        .scalars()
        .all()
    )
    return ApplicationDetail.model_validate(application).model_copy(
        update={
            **_read_fields(application, job, match),
            "events": [ApplicationEventRead.model_validate(e) for e in events],
        }
    )


async def _get_owned(
    db: AsyncSession, application_id: uuid.UUID, user_id: uuid.UUID
) -> Application:
    application = (
        await db.execute(
            select(Application).where(
                Application.id == application_id, Application.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if application is None:
        raise _NOT_FOUND
    return application


@router.post("", response_model=ApplicationDetail, status_code=status.HTTP_201_CREATED)
async def create_application(
    body: ApplicationCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApplicationDetail:
    job = (
        await db.execute(
            select(JobPosting).where(
                JobPosting.id == body.job_posting_id, JobPosting.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if job is None:
        raise _NOT_FOUND

    try:
        application = await application_service.create_application(
            db, user_id=user.id, job=job, notes=body.notes
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You're already tracking an application for this job.",
        ) from exc
    await db.refresh(application)
    return await _build_detail(db, application)


@router.get("", response_model=list[ApplicationRead])
async def list_applications(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    application_status: Annotated[ApplicationStatus | None, Query(alias="status")] = None,
) -> list[ApplicationRead]:
    query = select(Application).where(Application.user_id == user.id)
    if application_status is not None:
        query = query.where(Application.status == application_status)
    applications = list(
        (await db.execute(query.order_by(Application.updated_at.desc()))).scalars().all()
    )
    if not applications:
        return []

    job_ids = [a.job_posting_id for a in applications]
    jobs = {
        j.id: j
        for j in (await db.execute(select(JobPosting).where(JobPosting.id.in_(job_ids))))
        .scalars()
        .all()
    }
    matches = {
        m.job_posting_id: m
        for m in (await db.execute(select(JobMatch).where(JobMatch.job_posting_id.in_(job_ids))))
        .scalars()
        .all()
    }
    return [
        ApplicationRead.model_validate(a).model_copy(
            update=_read_fields(a, jobs.get(a.job_posting_id), matches.get(a.job_posting_id))
        )
        for a in applications
    ]


@router.get("/{application_id}", response_model=ApplicationDetail)
async def get_application(
    application_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApplicationDetail:
    return await _build_detail(db, await _get_owned(db, application_id, user.id))


@router.post("/{application_id}/status", response_model=ApplicationDetail)
async def change_application_status(
    application_id: uuid.UUID,
    body: ApplicationStatusChange,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApplicationDetail:
    application = await _get_owned(db, application_id, user.id)
    job = await db.get(JobPosting, application.job_posting_id)
    if job is None:  # can't happen while the FK cascades, but never assume
        raise _NOT_FOUND
    try:
        await application_service.change_status(
            db,
            application,
            job,
            to_status=body.status,
            occurred_on=body.occurred_on,
            note=body.note,
            user_id=user.id,
        )
    except ApplicationTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await db.commit()
    await db.refresh(application)
    return await _build_detail(db, application)


@router.post("/{application_id}/events", response_model=ApplicationDetail)
async def add_application_event(
    application_id: uuid.UUID,
    body: ApplicationEventCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApplicationDetail:
    application = await _get_owned(db, application_id, user.id)
    await application_service.add_event(
        db,
        application,
        event_type=body.event_type,
        occurred_on=body.occurred_on,
        body=body.body,
        user_id=user.id,
    )
    await db.commit()
    return await _build_detail(db, application)


@router.patch("/{application_id}", response_model=ApplicationDetail)
async def update_application(
    application_id: uuid.UUID,
    body: ApplicationUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApplicationDetail:
    application = await _get_owned(db, application_id, user.id)
    sent = body.model_fields_set  # so an explicit null clears a field, and omission doesn't
    if "notes" in sent:
        application.notes = body.notes or None
    if "next_action_text" in sent:
        application.next_action_text = body.next_action_text or None
    if "next_action_on" in sent:
        application.next_action_on = body.next_action_on
    # Field names only — notes can be personal, and the audit trail records *that* something
    # changed, not a second copy of what it was.
    await log_action(
        db,
        user_id=user.id,
        action="career.application.updated",
        risk_level="green",
        summary="Edited an application's notes or follow-up.",
        evidence={"fields": sorted(sent & {"notes", "next_action_text", "next_action_on"})},
        resource_type="application",
        resource_id=application.id,
    )
    await db.commit()
    await db.refresh(application)
    return await _build_detail(db, application)


@router.delete("/{application_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_application(
    application_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    application = await _get_owned(db, application_id, user.id)
    await log_action(
        db,
        user_id=user.id,
        action="career.application.deleted",
        risk_level="green",
        summary="Stopped tracking an application.",
        resource_type="application",
        resource_id=application.id,
        result={"last_status": application.status},
    )
    await db.delete(application)
    await db.commit()
