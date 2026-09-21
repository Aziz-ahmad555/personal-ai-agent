"""Application tracker operations. Green risk throughout: these are the user's own local
records — nothing is submitted, sent, or inferred — and each change is written to the audit
trail. The status rules themselves are plain code in app.career.application_rules."""

import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import log_action
from app.career.application_rules import (
    ApplicationTransitionError,
    is_reopen,
    validate_transition,
)
from app.career.models import (
    Application,
    ApplicationEvent,
    EmployerVerification,
    JobFraudAssessment,
    JobMatch,
    JobPosting,
)
from app.career.verification import employer_key_for


async def build_apply_snapshot(db: AsyncSession, job: JobPosting) -> dict[str, Any]:
    """The posting's match / fraud / employer state right now, frozen onto the "applied"
    event — so the record of what the user knew when applying can't drift as live values are
    recomputed later. Anything not yet computed is recorded as absent, not guessed."""
    match = (
        await db.execute(select(JobMatch).where(JobMatch.job_posting_id == job.id))
    ).scalar_one_or_none()
    fraud = (
        await db.execute(
            select(JobFraudAssessment).where(JobFraudAssessment.job_posting_id == job.id)
        )
    ).scalar_one_or_none()

    verification = None
    key = employer_key_for(company_name=job.company_name, company_domain=job.company_domain)
    if key:
        verification = (
            await db.execute(
                select(EmployerVerification).where(EmployerVerification.employer_key == key)
            )
        ).scalar_one_or_none()

    completed = match is not None and match.status == "completed"
    return {
        "captured_at": datetime.now(UTC).isoformat(),
        "match": (
            {
                "score_percent": match.score_percent,
                "assessed_weight": match.assessed_weight,
                "low_confidence": match.low_confidence,
            }
            if completed and match is not None
            else None
        ),
        "fraud_risk_level": fraud.risk_level if fraud else None,
        "employer_verification": verification.verification_status if verification else None,
    }


async def create_application(
    db: AsyncSession, *, user_id: uuid.UUID, job: JobPosting, notes: str | None
) -> Application:
    application = Application(
        user_id=user_id, job_posting_id=job.id, status="saved", notes=notes or None
    )
    db.add(application)
    await db.flush()
    db.add(
        ApplicationEvent(
            application_id=application.id,
            event_type="status_change",
            from_status=None,
            to_status="saved",
            occurred_on=date.today(),
        )
    )
    await db.flush()
    await log_action(
        db,
        user_id=user_id,
        action="career.application.created",
        risk_level="green",
        summary=f"Started tracking an application to '{job.title or 'a job posting'}'.",
        resource_type="application",
        resource_id=application.id,
        result={"status": "saved"},
    )
    return application


async def _reconcile_dates(db: AsyncSession, application: Application, when: date) -> None:
    """Keeps the timeline coherent when a status is logged with an earlier date than the
    events already there (e.g. recording an application days after sending it).

    The automatic initial "saved" event is dated the day tracking started — a date the user
    never supplied — so it's pulled back to `when` rather than left sitting after the event
    that followed it. Any *user-dated* status change that would end up before an earlier one
    is a real contradiction, and is rejected instead of silently rewritten."""
    status_events = (
        (
            await db.execute(
                select(ApplicationEvent).where(
                    ApplicationEvent.application_id == application.id,
                    ApplicationEvent.event_type == "status_change",
                    ApplicationEvent.occurred_on > when,
                )
            )
        )
        .scalars()
        .all()
    )
    if not status_events:
        return
    if all(e.from_status is None for e in status_events):
        for event in status_events:
            event.occurred_on = when
        return
    latest = max(e.occurred_on for e in status_events)
    raise ApplicationTransitionError(
        f"That date ({when.isoformat()}) is before an earlier status change on "
        f"{latest.isoformat()}. Use a date on or after it."
    )


async def change_status(
    db: AsyncSession,
    application: Application,
    job: JobPosting,
    *,
    to_status: str,
    occurred_on: date | None,
    note: str | None,
    user_id: uuid.UUID,
) -> ApplicationEvent:
    """Raises ApplicationTransitionError if the move isn't allowed."""
    from_status = application.status
    validate_transition(from_status, to_status)

    when = occurred_on or date.today()
    await _reconcile_dates(db, application, when)
    reopened = is_reopen(from_status, to_status)
    snapshot = None
    if to_status == "applied":
        application.applied_on = when
        snapshot = await build_apply_snapshot(db, job)

    application.status = to_status
    event = ApplicationEvent(
        application_id=application.id,
        event_type="status_change",
        from_status=from_status,
        to_status=to_status,
        occurred_on=when,
        body=note or None,
        snapshot=snapshot,
    )
    db.add(event)
    await db.flush()
    await log_action(
        db,
        user_id=user_id,
        action="career.application.reopened" if reopened else "career.application.status_changed",
        risk_level="green",
        summary=(
            f"Reopened an application: {from_status} -> {to_status}."
            if reopened
            else f"Moved an application: {from_status} -> {to_status}."
        ),
        resource_type="application",
        resource_id=application.id,
        result={"from": from_status, "to": to_status},
    )
    return event


async def add_event(
    db: AsyncSession,
    application: Application,
    *,
    event_type: str,
    occurred_on: date | None,
    body: str,
    user_id: uuid.UUID,
) -> ApplicationEvent:
    event = ApplicationEvent(
        application_id=application.id,
        event_type=event_type,
        occurred_on=occurred_on or date.today(),
        body=body,
    )
    db.add(event)
    await db.flush()
    await log_action(
        db,
        user_id=user_id,
        action=f"career.application.{event_type}_added",
        risk_level="green",
        summary=f"Added a {event_type} to an application's timeline.",
        resource_type="application",
        resource_id=application.id,
    )
    return event
