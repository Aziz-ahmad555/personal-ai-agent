"""Every risky action, automatic or not, is recorded here — never a side note in a log
line. Green actions call log_action once, after the fact, and are done. Yellow/Red actions
call request_approval first and must not perform their effect until decide_approval
returns an approved row (and, for red, a passing second_check_passed) — the caller is
responsible for actually withholding the effect; this module only tracks the decision.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import RISK_LEVELS, AuditLog
from app.audit.second_checks import SECOND_CHECKS


class ApprovalError(RuntimeError):
    """Raised when a decision can't be honored as requested — e.g. approving a red action
    without a passing second check, or deciding a row that isn't actually pending."""


async def log_action(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    action: str,
    risk_level: str,
    summary: str,
    evidence: dict[str, Any] | None = None,
    resource_type: str | None = None,
    resource_id: uuid.UUID | None = None,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> AuditLog:
    """For an action that already ran (green, or the executed effect of a previously
    approved yellow/red action) — recorded as a completed/failed fact, never a pending
    question."""
    if risk_level not in RISK_LEVELS:
        raise ValueError(f"Unknown risk_level: {risk_level!r}")

    log = AuditLog(
        user_id=user_id,
        action=action,
        risk_level=risk_level,
        status="failed" if error else "completed",
        summary=summary,
        evidence=evidence,
        resource_type=resource_type,
        resource_id=resource_id,
        result=result,
        error=error,
        decided_at=datetime.now(UTC),
        decided_by=user_id,
    )
    db.add(log)
    await db.flush()
    return log


async def request_approval(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    action: str,
    risk_level: str,
    summary: str,
    evidence: dict[str, Any] | None = None,
    resource_type: str | None = None,
    resource_id: uuid.UUID | None = None,
) -> AuditLog:
    """For a yellow/red action: records what is proposed and why, and stops there — the
    caller must not perform the action's effect until decide_approval returns an approved
    row for this log's id."""
    if risk_level == "green":
        raise ApprovalError("Green actions run automatically — call log_action, not this.")
    if risk_level not in RISK_LEVELS:
        raise ValueError(f"Unknown risk_level: {risk_level!r}")

    log = AuditLog(
        user_id=user_id,
        action=action,
        risk_level=risk_level,
        status="pending_approval",
        summary=summary,
        evidence=evidence,
        resource_type=resource_type,
        resource_id=resource_id,
    )
    db.add(log)
    await db.flush()
    return log


async def decide_approval(
    db: AsyncSession,
    *,
    audit_log_id: uuid.UUID,
    user_id: uuid.UUID,
    approved: bool,
) -> AuditLog:
    """The actual decision is a single atomic UPDATE...WHERE, not a SELECT-then-write: two
    concurrent decisions on the same row can no longer both read "pending_approval" and both
    proceed to write a (possibly conflicting) final state — the database's own row lock during
    the UPDATE serializes them, so only one can ever match the WHERE clause and actually change
    the row. The loser affects zero rows and gets a diagnostic-only SELECT afterward (see below)
    purely to word its error correctly — that SELECT never itself gates the decision.

    Approving a red-risk row is the one exception that needs a read first: whether it's honored
    depends on an independent second check (see app.audit.second_checks) keyed by the row's own
    `action`, which this function runs itself — never something the API caller can assert (that
    was the whole gap: previously `second_check_passed` was just a client-supplied boolean).
    That read never decides anything by itself — it can't, since the actual state transition is
    still gated by the atomic UPDATE below, so two concurrent approvals of the same row still
    can't both succeed."""
    second_check_passed: bool | None = None

    if approved:
        pending = (
            await db.execute(
                select(AuditLog).where(
                    AuditLog.id == audit_log_id,
                    AuditLog.user_id == user_id,
                    AuditLog.status == "pending_approval",
                )
            )
        ).scalar_one_or_none()
        if pending is not None and pending.risk_level == "red":
            check = SECOND_CHECKS.get(pending.action)
            if check is None:
                raise ApprovalError(
                    "No independent second check is registered for this action; a red-risk "
                    "action cannot be approved without one."
                )
            if not await check(db, pending):
                raise ApprovalError(
                    "The independent second check did not pass; approval was not honored."
                )
            second_check_passed = True

    # .returning(AuditLog), executed through the ORM session, hands back a properly
    # session-synced object — unlike a plain Core UPDATE followed by db.get(), which would
    # silently return a stale, already-loaded copy from the identity map instead of reflecting
    # what was just written.
    result = await db.execute(
        update(AuditLog)
        .where(
            AuditLog.id == audit_log_id,
            AuditLog.user_id == user_id,
            AuditLog.status == "pending_approval",
        )
        .values(
            status="approved" if approved else "rejected",
            decided_at=datetime.now(UTC),
            decided_by=user_id,
            second_check_passed=second_check_passed,
        )
        .returning(AuditLog)
    )
    updated = result.scalar_one_or_none()
    if updated is None:
        # The write already didn't happen — this is only to word the (still safe, still
        # non-disclosing for a foreign row) error correctly, never a second gate.
        log = (
            await db.execute(
                select(AuditLog).where(AuditLog.id == audit_log_id, AuditLog.user_id == user_id)
            )
        ).scalar_one_or_none()
        if log is None:
            raise ApprovalError("No such pending action for this user.")
        raise ApprovalError(f"Action is already {log.status}, not pending.")

    await db.flush()
    return updated


async def record_result(
    db: AsyncSession,
    *,
    audit_log_id: uuid.UUID,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> AuditLog:
    """After an approved yellow/red action's effect has actually executed, records what
    happened. Kept distinct from decide_approval so "the user said yes" and "the system
    then did X" are never the same row transition."""
    log = await db.get(AuditLog, audit_log_id)
    if log is None:
        raise ApprovalError("No such audit log.")
    log.status = "failed" if error else "completed"
    log.result = result
    log.error = error
    await db.flush()
    return log
