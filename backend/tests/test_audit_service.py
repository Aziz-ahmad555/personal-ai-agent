import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.models import AuditLog
from app.audit.service import (
    ApprovalError,
    decide_approval,
    log_action,
    record_result,
    request_approval,
)
from app.db.models import User


async def _make_user(db: AsyncSession) -> User:
    user = User(email=f"audit-test-{uuid.uuid4()}@example.com", hashed_password="x")
    db.add(user)
    await db.flush()
    return user


async def test_log_action_records_a_completed_green_action(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as db:
        user = await _make_user(db)
        log = await log_action(
            db,
            user_id=user.id,
            action="career.job.captured_from_url",
            risk_level="green",
            summary="Captured a job posting.",
            evidence={"url": "https://acme.example.com/careers/1"},
            resource_type="job_posting",
            resource_id=uuid.uuid4(),
        )
        await db.commit()

        assert log.status == "completed"
        assert log.decided_at is not None
        assert log.decided_by == user.id


async def test_log_action_with_error_records_failed_status(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as db:
        user = await _make_user(db)
        log = await log_action(
            db,
            user_id=user.id,
            action="career.feed.poll_failed",
            risk_level="green",
            summary="Polling failed.",
            error="boom",
        )
        assert log.status == "failed"
        assert log.error == "boom"


async def test_request_approval_rejects_green_risk(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as db:
        user = await _make_user(db)
        with pytest.raises(ApprovalError):
            await request_approval(
                db, user_id=user.id, action="x", risk_level="green", summary="s"
            )


async def test_yellow_action_stays_pending_until_decided(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as db:
        user = await _make_user(db)
        pending = await request_approval(
            db,
            user_id=user.id,
            action="gmail.send_draft",
            risk_level="yellow",
            summary="Send a drafted reply.",
            evidence={"to": "someone@example.com"},
        )
        await db.commit()
        assert pending.status == "pending_approval"

        approved = await decide_approval(
            db, audit_log_id=pending.id, user_id=user.id, approved=True
        )
        await db.commit()
        assert approved.status == "approved"
        assert approved.decided_by == user.id


async def test_deciding_an_already_decided_action_raises(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as db:
        user = await _make_user(db)
        pending = await request_approval(
            db, user_id=user.id, action="x", risk_level="yellow", summary="s"
        )
        await decide_approval(db, audit_log_id=pending.id, user_id=user.id, approved=True)
        await db.commit()

        with pytest.raises(ApprovalError):
            await decide_approval(db, audit_log_id=pending.id, user_id=user.id, approved=True)


async def test_red_action_requires_second_check_to_approve(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as db:
        user = await _make_user(db)
        pending = await request_approval(
            db,
            user_id=user.id,
            action="career.application.submit",
            risk_level="red",
            summary="Submit an application.",
        )
        await db.commit()

        with pytest.raises(ApprovalError):
            await decide_approval(
                db,
                audit_log_id=pending.id,
                user_id=user.id,
                approved=True,
                second_check_passed=False,
            )

        approved = await decide_approval(
            db,
            audit_log_id=pending.id,
            user_id=user.id,
            approved=True,
            second_check_passed=True,
        )
        assert approved.status == "approved"
        assert approved.second_check_passed is True


async def test_a_red_action_can_still_be_rejected_without_a_second_check(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The second-check requirement gates approval, not rejection — saying no to a risky
    action should never itself require extra verification."""
    async with session_factory() as db:
        user = await _make_user(db)
        pending = await request_approval(
            db, user_id=user.id, action="x", risk_level="red", summary="s"
        )
        rejected = await decide_approval(
            db, audit_log_id=pending.id, user_id=user.id, approved=False
        )
        assert rejected.status == "rejected"


async def test_decide_approval_scopes_to_the_requesting_user(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as db:
        owner = await _make_user(db)
        other = await _make_user(db)
        pending = await request_approval(
            db, user_id=owner.id, action="x", risk_level="yellow", summary="s"
        )
        await db.commit()

        with pytest.raises(ApprovalError):
            await decide_approval(db, audit_log_id=pending.id, user_id=other.id, approved=True)


async def test_record_result_marks_the_executed_effect(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as db:
        user = await _make_user(db)
        pending = await request_approval(
            db, user_id=user.id, action="x", risk_level="yellow", summary="s"
        )
        await decide_approval(db, audit_log_id=pending.id, user_id=user.id, approved=True)
        await db.commit()

        done = await record_result(db, audit_log_id=pending.id, result={"sent": True})
        assert done.status == "completed"
        assert done.result == {"sent": True}

        failed = await record_result(db, audit_log_id=pending.id, error="network error")
        assert failed.status == "failed"
        assert failed.error == "network error"


async def test_audit_log_row_is_never_deleted_by_a_decision(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as db:
        user = await _make_user(db)
        pending = await request_approval(
            db, user_id=user.id, action="x", risk_level="yellow", summary="original summary"
        )
        await decide_approval(db, audit_log_id=pending.id, user_id=user.id, approved=False)
        await db.commit()

        row = await db.get(AuditLog, pending.id)
        assert row is not None
        assert row.summary == "original summary"
        assert row.status == "rejected"
