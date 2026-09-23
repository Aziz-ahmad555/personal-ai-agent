"""Reads events on the user's primary calendar into a local snapshot and classifies each one
deterministically (see detect.py). Read-only against Google, and it never edits an application
or the calendar itself — it only proposes a link, which a sync keeps refreshed for events it
touches, unless the user already confirmed a classification, which is never overwritten.

Two sync types, the same shape as Gmail's:
- full: no stored sync_token yet (or Google rejected the one we had) — lists a bounded window
  (FULL_SYNC_PAST_DAYS back, FULL_SYNC_FUTURE_DAYS forward) and stores every event in it.
- incremental: uses Google's syncToken from the last full/incremental list — far cheaper, and
  the only way a later sync sees events that were edited or cancelled since.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import log_action
from app.calendar import client as gcal
from app.calendar.detect import ApplicationCandidate, classify_event, find_application_match
from app.calendar.models import CalendarConnection, CalendarEvent, CalendarSyncRun
from app.calendar.service import NotConnectedError, get_valid_access_token
from app.career.models import Application, JobPosting
from app.logging import get_logger

logger = get_logger(__name__)

FULL_SYNC_PAST_DAYS = 30
FULL_SYNC_FUTURE_DAYS = 180
# events.list pages of up to 250 each — generous for a personal calendar, bounded so one sync
# can't run away against an unusually large or noisy one.
MAX_REQUESTS = 50

# The background task lives inside the server process, so a restart silently kills it. A run
# still "running" long after it started is reported as failed, detected on read.
SYNC_TIMEOUT = timedelta(minutes=10)
STALLED_MESSAGE = (
    "This sync didn't finish — the server was probably restarted while it was running. Try again."
)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def is_active(run: CalendarSyncRun, *, now: datetime | None = None) -> bool:
    if run.status not in ("pending", "running"):
        return False
    return (now or datetime.now(UTC)) - _aware(run.started_at) <= SYNC_TIMEOUT


def is_stalled(run: CalendarSyncRun, *, now: datetime | None = None) -> bool:
    if run.status not in ("pending", "running"):
        return False
    return (now or datetime.now(UTC)) - _aware(run.started_at) > SYNC_TIMEOUT


async def start_run(db: AsyncSession, connection_id: uuid.UUID) -> CalendarSyncRun:
    run = CalendarSyncRun(connection_id=connection_id, status="pending")
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return run


async def run_sync(db: AsyncSession, run_id: uuid.UUID, *, trigger: str = "manual") -> None:
    run = await db.get(CalendarSyncRun, run_id)
    if run is None:
        logger.warning("calendar_sync_run_not_found", run_id=str(run_id))
        return
    connection_id = run.connection_id
    connection = await db.get(CalendarConnection, connection_id)
    if connection is None:
        await _fail(db, run_id, "The Calendar connection no longer exists.", trigger=trigger)
        return

    run.status = "running"
    run.started_at = datetime.now(UTC)
    await db.commit()

    try:
        token = await get_valid_access_token(db, connection)
    except Exception as exc:  # noqa: BLE001 — every failure is reported on the run
        await _fail(db, run_id, _describe(exc), trigger=trigger)
        return

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            await _sync(db, run, connection, client, token, trigger=trigger)
    except gcal.CalendarAuthError:
        await _fail(
            db,
            run_id,
            "Google rejected the access token — reconnect Calendar.",
            needs_reauth=True,
            trigger=trigger,
        )
    except Exception as exc:  # noqa: BLE001 — a background task must record, not raise
        logger.warning("calendar_sync_failed", error=str(exc))
        await _fail(db, run_id, _describe(exc), trigger=trigger)


def _describe(exc: Exception) -> str:
    if isinstance(exc, gcal.CalendarApiError | NotConnectedError):
        return str(exc)
    return "Something went wrong while syncing. Try again."


async def _fail(
    db: AsyncSession,
    run_id: uuid.UUID,
    message: str,
    *,
    needs_reauth: bool = False,
    trigger: str = "manual",
) -> None:
    # Plain values only past this point: a failed flush rolls the session back and expires
    # every object in it, so this must not depend on attributes read before the rollback.
    await db.rollback()
    run = await db.get(CalendarSyncRun, run_id)
    if run is None:
        return
    run.status = "failed"
    run.error = message
    run.completed_at = datetime.now(UTC)
    connection = await db.get(CalendarConnection, run.connection_id)
    if connection is not None:
        if needs_reauth:
            connection.status = "needs_reauth"
            connection.last_error = "Google rejected the access token."
        await log_action(
            db,
            user_id=connection.user_id,
            action="calendar.sync_failed",
            risk_level="green",
            summary="Calendar sync did not complete.",
            error=message,
            evidence={"trigger": trigger},
            resource_type="calendar_sync_run",
            resource_id=run.id,
        )
    await db.commit()


async def _application_candidates(
    db: AsyncSession, user_id: uuid.UUID
) -> list[ApplicationCandidate]:
    rows = await db.execute(
        select(Application.id, JobPosting.company_name, JobPosting.company_domain)
        .join(JobPosting, Application.job_posting_id == JobPosting.id)
        .where(Application.user_id == user_id)
    )
    return [
        ApplicationCandidate(str(app_id), company_name, company_domain)
        for app_id, company_name, company_domain in rows.all()
    ]


def _parse_event_time(value: dict[str, Any] | None) -> tuple[datetime | None, bool]:
    """Google represents an all-day event's date/time as {"date": "YYYY-MM-DD"} and a timed
    one as {"dateTime": "...", "timeZone": "..."}. Returns (when, is_all_day)."""
    if not value:
        return None, False
    if "dateTime" in value:
        raw = str(value["dateTime"]).replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(raw), False
        except ValueError:
            return None, False
    if "date" in value:
        try:
            return datetime.fromisoformat(str(value["date"])).replace(tzinfo=UTC), True
        except ValueError:
            return None, True
    return None, False


def _attendees_of(raw: dict[str, Any]) -> list[dict[str, Any]]:
    attendees = raw.get("attendees")
    if not isinstance(attendees, list):
        return []
    return [
        {
            "email": a.get("email"),
            "display_name": a.get("displayName"),
            "response_status": a.get("responseStatus"),
        }
        for a in attendees
        if isinstance(a, dict) and a.get("email")
    ]


async def _upsert_event(
    db: AsyncSession,
    connection: CalendarConnection,
    raw: dict[str, Any],
    candidates: list[ApplicationCandidate],
) -> bool:
    """Returns True if this event is new to us."""
    google_event_id = str(raw.get("id", ""))
    row = (
        await db.execute(
            select(CalendarEvent).where(
                CalendarEvent.connection_id == connection.id,
                CalendarEvent.google_event_id == google_event_id,
            )
        )
    ).scalar_one_or_none()
    is_new = row is None
    if row is None:
        row = CalendarEvent(connection_id=connection.id, google_event_id=google_event_id)
        db.add(row)

    summary = raw.get("summary")
    description = raw.get("description")
    start_at, is_all_day = _parse_event_time(raw.get("start"))
    end_at, _ = _parse_event_time(raw.get("end"))
    attendees = _attendees_of(raw)
    organizer_email = (raw.get("organizer") or {}).get("email")

    row.html_link = raw.get("htmlLink")
    row.summary = summary
    row.description = description
    row.location = raw.get("location")
    row.start_at = start_at
    row.end_at = end_at
    row.is_all_day = is_all_day
    row.organizer_email = organizer_email
    row.attendees = attendees
    row.synced_at = datetime.now(UTC)

    # A user's own correction is never silently overwritten by the next sync — only the raw
    # calendar facts above are refreshed.
    if not row.user_confirmed:
        kind, reason = classify_event(summary, description)
        row.kind = kind
        row.match_reason = reason
        match = find_application_match(
            summary=summary,
            description=description,
            attendees=attendees,
            organizer_email=organizer_email,
            candidates=candidates,
        )
        row.application_id = uuid.UUID(match.application_id) if match else None
        row.application_match_reason = match.reason if match else None

    await db.flush()
    return is_new


async def _sync(
    db: AsyncSession,
    run: CalendarSyncRun,
    connection: CalendarConnection,
    client: httpx.AsyncClient,
    token: str,
    *,
    trigger: str = "manual",
) -> None:
    candidates = await _application_candidates(db, connection.user_id)
    now = datetime.now(UTC)
    time_min = (now - timedelta(days=FULL_SYNC_PAST_DAYS)).isoformat()
    time_max = (now + timedelta(days=FULL_SYNC_FUTURE_DAYS)).isoformat()

    incremental = connection.sync_token is not None
    sync_token = connection.sync_token
    page_token: str | None = None
    next_sync_token: str | None = None
    requests_made = 0
    seen_ids: set[str] = set()
    new_count = 0
    warnings: list[str] = []

    while True:
        if requests_made >= MAX_REQUESTS:
            warnings.append(
                f"Stopped early after {requests_made} requests, this sync's limit. "
                "Sync again to pick up where it left off."
            )
            break
        try:
            page = await gcal.list_events(
                client,
                token,
                time_min=None if incremental else time_min,
                time_max=None if incremental else time_max,
                sync_token=sync_token if incremental else None,
                page_token=page_token,
            )
        except gcal.SyncTokenExpiredError:
            # Google no longer has history back to our cursor — start over with a full sync.
            incremental = False
            sync_token = None
            page_token = None
            connection.sync_token = None
            warnings.append("The saved sync position expired, so this ran as a full sync.")
            continue
        requests_made += 1

        for event in page.events:
            event_id = str(event.get("id", ""))
            if not event_id:
                continue
            seen_ids.add(event_id)
            if event.get("status") == "cancelled":
                await db.execute(
                    delete(CalendarEvent).where(
                        CalendarEvent.connection_id == connection.id,
                        CalendarEvent.google_event_id == event_id,
                    )
                )
                continue
            if await _upsert_event(db, connection, event, candidates):
                new_count += 1

        if page.next_sync_token:
            next_sync_token = page.next_sync_token
        if not page.next_page_token:
            break
        page_token = page.next_page_token

    if next_sync_token:
        connection.sync_token = next_sync_token
    connection.last_synced_at = datetime.now(UTC)
    run.events_seen = len(seen_ids)
    run.events_stored = new_count
    run.warnings = warnings
    run.status = "completed"
    run.completed_at = datetime.now(UTC)
    await log_action(
        db,
        user_id=connection.user_id,
        action="calendar.synced",
        risk_level="green",
        summary=f"Synced {len(seen_ids)} calendar events ({new_count} new).",
        evidence={
            "events_seen": len(seen_ids),
            "events_new": new_count,
            "requests_made": requests_made,
            "incremental": incremental,
            "warnings": warnings,
            "trigger": trigger,
        },
        resource_type="calendar_sync_run",
        resource_id=run.id,
    )
    await db.commit()
