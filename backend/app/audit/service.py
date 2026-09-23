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
    second_check_passed: bool = False,
) -> AuditLog:
    """A single atomic UPDATE...WHERE, not a SELECT-then-write: two concurrent decisions on
    the same row can no longer both read "pending_approval" and both proceed to write a
    (possibly conflicting) final state — the database's own row lock during the UPDATE
    serializes them, so only one can ever match the WHERE clause and actually change the row.
    The loser affects zero rows and gets a diagnostic-only SELECT afterward (see below) purely
    to word its error correctly — that SELECT never itself gates the decision."""
    where_clauses = [
        AuditLog.id == audit_log_id,
        AuditLog.user_id == user_id,
        AuditLog.status == "pending_approval",
    ]
    if approved and not second_check_passed:
        # Without a passing second check, only a non-red row can match — a red row simply
        # won't be updated, and the diagnostic SELECT below turns that into the right message.
        where_clauses.append(AuditLog.risk_level != "red")

    # .returning(AuditLog), executed through the ORM session, hands back a properly
    # session-synced object — unlike a plain Core UPDATE followed by db.get(), which would
    # silently return a stale, already-loaded copy from the identity map instead of reflecting
    # what was just written.
    result = await db.execute(
        update(AuditLog)
        .where(*where_clauses)
        .values(
            status="approved" if approved else "rejected",
            decided_at=datetime.now(UTC),
            decided_by=user_id,
            second_check_passed=second_check_passed if approved else None,
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
        if log.status != "pending_approval":
            raise ApprovalError(f"Action is already {log.status}, not pending.")
        raise ApprovalError(
            "Red-risk actions require an independent second check to pass before approval "
            "can be honored."
        )

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
