"""Application tracker API tests: the lifecycle, the rules being enforced server-side, the
snapshot frozen at "applied", PATCH clear-vs-omit semantics, and per-user isolation."""

import uuid
from datetime import date, timedelta

from conftest import utc_today
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.models import AuditLog
from app.auth.security import hash_password
from app.career.models import (
    EmployerVerification,
    JobFraudAssessment,
    JobMatch,
    JobPosting,
)
from app.db.models import User

OWNER = "profile-owner@example.com"


async def _make_job(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    email: str = OWNER,
    title: str = "ML Engineer",
    company: str = "Acme Corp",
) -> str:
    async with session_factory() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one()
        job = JobPosting(
            user_id=user.id,
            source_channel="manual_paste",
            title=title,
            company_name=company,
            remote_type="remote",
        )
        db.add(job)
        await db.commit()
        return str(job.id)


async def _track(client: AsyncClient, headers: dict[str, str], job_id: str) -> dict:
    response = await client.post(
        "/career/applications", headers=headers, json={"job_posting_id": job_id}
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _move(
    client: AsyncClient, headers: dict[str, str], app_id: str, status: str, **extra: object
):
    return await client.post(
        f"/career/applications/{app_id}/status", headers=headers, json={"status": status, **extra}
    )


async def test_create_starts_saved_with_a_timeline_and_the_allowed_moves(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    job_id = await _make_job(session_factory)

    application = await _track(client, auth_headers, job_id)

    assert application["status"] == "saved"
    assert application["job"]["title"] == "ML Engineer"
    assert application["allowed_transitions"] == ["applied", "withdrawn"]
    assert application["reopen_targets"] == []
    assert [(e["from_status"], e["to_status"]) for e in application["events"]] == [(None, "saved")]


async def test_tracking_the_same_job_twice_is_a_conflict(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    job_id = await _make_job(session_factory)
    await _track(client, auth_headers, job_id)

    again = await client.post(
        "/career/applications", headers=auth_headers, json={"job_posting_id": job_id}
    )

    assert again.status_code == 409
    assert "already tracking" in again.json()["detail"]


async def test_cannot_track_a_job_that_isnt_yours_or_doesnt_exist(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as db:
        db.add(User(email="other@example.com", hashed_password=hash_password("x-y-z-123456")))
        await db.commit()
    others_job = await _make_job(session_factory, email="other@example.com")

    for job_id in (others_job, str(uuid.uuid4())):
        response = await client.post(
            "/career/applications", headers=auth_headers, json={"job_posting_id": job_id}
        )
        assert response.status_code == 404


async def test_applying_records_the_users_date_and_freezes_a_snapshot(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    job_id = await _make_job(session_factory)
    async with session_factory() as db:
        job = await db.get(JobPosting, uuid.UUID(job_id))
        assert job is not None
        match = JobMatch(
            job_posting_id=job.id,
            status="completed",
            score_percent=72,
            assessed_weight=40,
            low_confidence=True,
        )
        db.add(match)
        db.add(JobFraudAssessment(job_posting_id=job.id, risk_level="medium", risk_score=30))
        db.add(
            EmployerVerification(
                employer_key="name:acme corp",
                verification_status="unconfirmed",
                confidence_score=10,
                rationale="none found",
            )
        )
        await db.commit()
    application = await _track(client, auth_headers, job_id)
    applied_on = (utc_today() - timedelta(days=3)).isoformat()

    moved = await _move(client, auth_headers, application["id"], "applied", occurred_on=applied_on)

    assert moved.status_code == 200
    body = moved.json()
    assert body["status"] == "applied"
    assert body["applied_on"] == applied_on
    applied_event = body["events"][-1]
    assert applied_event["occurred_on"] == applied_on
    assert applied_event["snapshot"]["match"] == {
        "score_percent": 72,
        "assessed_weight": 40,
        "low_confidence": True,
    }
    assert applied_event["snapshot"]["fraud_risk_level"] == "medium"
    assert applied_event["snapshot"]["employer_verification"] == "unconfirmed"

    # The live match is recomputed later; what the user knew when applying must not change.
    async with session_factory() as db:
        live = (await db.execute(select(JobMatch))).scalar_one()
        live.score_percent = 15
        await db.commit()
    fetched = await client.get(f"/career/applications/{application['id']}", headers=auth_headers)
    detail = fetched.json()
    assert detail["events"][-1]["snapshot"]["match"]["score_percent"] == 72
    assert detail["match"]["score_percent"] == 15  # the card shows the current one


async def test_snapshot_records_absence_rather_than_guessing(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    job_id = await _make_job(session_factory)
    application = await _track(client, auth_headers, job_id)

    body = (await _move(client, auth_headers, application["id"], "applied")).json()

    snapshot = body["events"][-1]["snapshot"]
    assert snapshot["match"] is None
    assert snapshot["fraud_risk_level"] is None
    assert snapshot["employer_verification"] is None


async def test_invalid_moves_are_rejected_with_an_explanation(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    job_id = await _make_job(session_factory)
    application = await _track(client, auth_headers, job_id)

    skip = await _move(client, auth_headers, application["id"], "offer")

    assert skip.status_code == 409
    assert "Mark the application as 'applied' first" in skip.json()["detail"]
    unchanged = (
        await client.get(f"/career/applications/{application['id']}", headers=auth_headers)
    ).json()
    assert unchanged["status"] == "saved"
    assert len(unchanged["events"]) == 1


async def test_future_dates_are_rejected(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    job_id = await _make_job(session_factory)
    application = await _track(client, auth_headers, job_id)
    future = (utc_today() + timedelta(days=30)).isoformat()

    response = await _move(client, auth_headers, application["id"], "applied", occurred_on=future)

    assert response.status_code == 422


async def test_closing_then_explicitly_reopening(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    job_id = await _make_job(session_factory)
    app_id = (await _track(client, auth_headers, job_id))["id"]
    await _move(client, auth_headers, app_id, "applied")
    closed = (await _move(client, auth_headers, app_id, "no_response")).json()

    assert closed["allowed_transitions"] == []
    assert closed["reopen_targets"] == ["applied", "screening", "interviewing", "offer"]
    assert (await _move(client, auth_headers, app_id, "saved")).status_code == 409

    reopened = await _move(client, auth_headers, app_id, "interviewing", note="They replied!")

    assert reopened.status_code == 200
    body = reopened.json()
    assert body["status"] == "interviewing"
    assert body["events"][-1]["body"] == "They replied!"
    async with session_factory() as db:
        actions = set((await db.execute(select(AuditLog.action))).scalars().all())
    assert "career.application.reopened" in actions
    assert "career.application.status_changed" in actions


async def test_accepted_is_final(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    job_id = await _make_job(session_factory)
    app_id = (await _track(client, auth_headers, job_id))["id"]
    for step in ("applied", "offer", "accepted"):
        assert (await _move(client, auth_headers, app_id, step)).status_code == 200

    response = await _move(client, auth_headers, app_id, "interviewing")

    assert response.status_code == 409
    assert "final" in response.json()["detail"]


async def test_timeline_orders_by_the_date_things_happened(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    job_id = await _make_job(session_factory)
    app_id = (await _track(client, auth_headers, job_id))["id"]
    # Local date.today(), not utc_today(): must land on the same calendar day as the
    # "saved" event _track's own POST auto-creates, which app.career.application_service
    # also dates with local date.today() (deliberate there — a personal timeline reads
    # naturally in the user's own day, not UTC's) — using utc_today() here instead would
    # desync from it for several hours a day and turn this same-day tie-break into a test
    # of a different day entirely.
    today = date.today()
    # Logged later than it happened: the earlier date must sort first.
    await client.post(
        f"/career/applications/{app_id}/events",
        headers=auth_headers,
        json={"event_type": "interview", "occurred_on": today.isoformat(), "body": "Phone screen"},
    )
    response = await client.post(
        f"/career/applications/{app_id}/events",
        headers=auth_headers,
        json={
            "event_type": "note",
            "occurred_on": (today - timedelta(days=5)).isoformat(),
            "body": "Recruiter emailed first",
        },
    )

    assert response.status_code == 200
    bodies = [e["body"] for e in response.json()["events"]]
    # Ordered by when things happened, ties by when they were recorded: the note is dated
    # earlier than the day tracking began, so it comes first.
    assert bodies == ["Recruiter emailed first", None, "Phone screen"]


async def test_events_reject_empty_bodies_and_unknown_types(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    job_id = await _make_job(session_factory)
    app_id = (await _track(client, auth_headers, job_id))["id"]

    empty = await client.post(
        f"/career/applications/{app_id}/events",
        headers=auth_headers,
        json={"event_type": "note", "body": ""},
    )
    # Status changes must go through /status, where the rules are enforced.
    sneaky = await client.post(
        f"/career/applications/{app_id}/events",
        headers=auth_headers,
        json={"event_type": "status_change", "body": "offer!"},
    )

    assert empty.status_code == 422
    assert sneaky.status_code == 422


async def test_follow_up_states_and_patch_clear_versus_omit(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    job_id = await _make_job(session_factory)
    app_id = (await _track(client, auth_headers, job_id))["id"]
    await _move(client, auth_headers, app_id, "applied")
    url = f"/career/applications/{app_id}"
    today = utc_today()

    overdue = await client.patch(
        url,
        headers=auth_headers,
        json={
            "next_action_text": "Email the recruiter",
            "next_action_on": (today - timedelta(days=2)).isoformat(),
        },
    )
    assert overdue.json()["follow_up_state"] == "overdue"

    due_today = await client.patch(
        url, headers=auth_headers, json={"next_action_on": today.isoformat()}
    )
    assert due_today.json()["follow_up_state"] == "due_today"
    assert due_today.json()["next_action_text"] == "Email the recruiter"  # omitted -> untouched

    notes_only = await client.patch(url, headers=auth_headers, json={"notes": "Referred by Sam"})
    assert notes_only.json()["next_action_on"] == today.isoformat()  # still there
    assert notes_only.json()["notes"] == "Referred by Sam"

    cleared = await client.patch(
        url, headers=auth_headers, json={"next_action_on": None, "next_action_text": None}
    )
    assert cleared.json()["follow_up_state"] is None
    assert cleared.json()["next_action_text"] is None


async def test_closed_application_stops_nagging(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    job_id = await _make_job(session_factory)
    app_id = (await _track(client, auth_headers, job_id))["id"]
    await _move(client, auth_headers, app_id, "applied")
    await client.patch(
        f"/career/applications/{app_id}",
        headers=auth_headers,
        json={"next_action_on": (utc_today() - timedelta(days=9)).isoformat()},
    )

    closed = await _move(client, auth_headers, app_id, "rejected")

    assert closed.json()["follow_up_state"] is None


async def test_list_filters_by_status_and_carries_job_and_match(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    first = await _make_job(session_factory, title="Role A", company="A Co")
    second = await _make_job(session_factory, title="Role B", company="B Co")
    async with session_factory() as db:
        db.add(
            JobMatch(
                job_posting_id=uuid.UUID(first),
                status="completed",
                score_percent=64,
                assessed_weight=85,
                low_confidence=False,
            )
        )
        await db.commit()
    a = (await _track(client, auth_headers, first))["id"]
    await _track(client, auth_headers, second)
    await _move(client, auth_headers, a, "applied")

    everything = (await client.get("/career/applications", headers=auth_headers)).json()
    applied = (await client.get("/career/applications?status=applied", headers=auth_headers)).json()
    bad = await client.get("/career/applications?status=bogus", headers=auth_headers)

    assert len(everything) == 2
    assert [x["job"]["title"] for x in applied] == ["Role A"]
    assert applied[0]["match"] == {"score_percent": 64, "low_confidence": False}
    assert bad.status_code == 422


async def test_other_users_applications_are_invisible(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as db:
        other = User(email="other@example.com", hashed_password=hash_password("x-y-z-123456"))
        db.add(other)
        await db.commit()
        job = JobPosting(user_id=other.id, source_channel="manual_paste", title="T")
        db.add(job)
        await db.commit()
        from app.career.models import Application

        foreign = Application(user_id=other.id, job_posting_id=job.id, status="saved")
        db.add(foreign)
        await db.commit()
        foreign_id = str(foreign.id)

    assert (await client.get("/career/applications", headers=auth_headers)).json() == []
    for method, path in (
        ("get", f"/career/applications/{foreign_id}"),
        ("delete", f"/career/applications/{foreign_id}"),
    ):
        assert (await getattr(client, method)(path, headers=auth_headers)).status_code == 404
    assert (await _move(client, auth_headers, foreign_id, "applied")).status_code == 404


async def test_delete_removes_the_application_but_not_the_job(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    job_id = await _make_job(session_factory)
    app_id = (await _track(client, auth_headers, job_id))["id"]

    gone = await client.delete(f"/career/applications/{app_id}", headers=auth_headers)

    assert gone.status_code == 204
    missing = await client.get(f"/career/applications/{app_id}", headers=auth_headers)
    assert missing.status_code == 404
    assert (await client.get(f"/career/jobs/{job_id}", headers=auth_headers)).status_code == 200
    async with session_factory() as db:
        actions = set((await db.execute(select(AuditLog.action))).scalars().all())
    assert "career.application.deleted" in actions


async def test_logging_an_application_after_the_fact_keeps_the_timeline_in_order(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    job_id = await _make_job(session_factory)
    app_id = (await _track(client, auth_headers, job_id))["id"]
    applied_on = (utc_today() - timedelta(days=4)).isoformat()

    body = (await _move(client, auth_headers, app_id, "applied", occurred_on=applied_on)).json()

    # "saved" was dated the day tracking started, which the user never chose; it must not
    # end up after the application it preceded.
    assert [(e["to_status"], e["occurred_on"]) for e in body["events"]] == [
        ("saved", applied_on),
        ("applied", applied_on),
    ]


async def test_a_status_date_before_the_previous_status_change_is_rejected(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    job_id = await _make_job(session_factory)
    app_id = (await _track(client, auth_headers, job_id))["id"]
    await _move(client, auth_headers, app_id, "applied", occurred_on=utc_today().isoformat())
    too_early = (utc_today() - timedelta(days=10)).isoformat()

    response = await _move(client, auth_headers, app_id, "screening", occurred_on=too_early)

    assert response.status_code == 409
    assert "before an earlier status change" in response.json()["detail"]
    unchanged = (await client.get(f"/career/applications/{app_id}", headers=auth_headers)).json()
    assert unchanged["status"] == "applied"


async def test_editing_notes_or_follow_up_is_audited_without_copying_the_notes(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    job_id = await _make_job(session_factory)
    app_id = (await _track(client, auth_headers, job_id))["id"]

    await client.patch(
        f"/career/applications/{app_id}",
        headers=auth_headers,
        json={"notes": "Private thoughts about the salary", "next_action_text": "Call back"},
    )

    async with session_factory() as db:
        entry = (
            await db.execute(
                select(AuditLog).where(AuditLog.action == "career.application.updated")
            )
        ).scalar_one()
    assert entry.evidence == {"fields": ["next_action_text", "notes"]}
    assert "Private thoughts" not in str(entry.evidence) + entry.summary
