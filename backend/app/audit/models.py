import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# Green: automatic, no confirmation needed. Yellow: user confirms before it runs. Red:
# explicit confirmation *and* a second independent check (see AuditLog.second_check_passed)
# — never assigned by the action's own code, since that would let a bug misclassify its
# own risk (CLAUDE.md: "Every risky action is Green / Yellow / Red").
RISK_LEVELS = ("green", "yellow", "red")

# pending_approval: a yellow/red action is waiting on the user (see request_approval).
# approved / rejected: the user's decision on a pending_approval row (see decide_approval).
# completed / failed: a green action that already ran, or the executed effect of an
# approved yellow/red action (see log_action / record_result).
ACTION_STATUSES = ("pending_approval", "approved", "rejected", "completed", "failed")


class AuditLog(Base):
    """Append-only record of every risky action the system takes or proposes, per
    CLAUDE.md's "Audit everything: what, why, evidence, risk level, user decision, result."
    A row is never mutated to hide what was originally proposed — decide_approval and
    record_result only ever add fields (status/decided_at/result), never rewrite summary
    or evidence."""

    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    risk_level: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="completed", nullable=False)

    summary: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    # What this action was about, when it concerns a specific row elsewhere (e.g.
    # "job_posting" / a JobPosting.id) — optional, since some actions (a feed poll) concern
    # a whole operation rather than one resource.
    resource_type: Mapped[str | None] = mapped_column(String(50))
    resource_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)

    # Red-risk actions require this to be explicitly True — set by a check that is not the
    # same code path that proposed the action — before decide_approval will honor
    # approved=True. Still null for green/yellow rows and for red rows not yet decided.
    second_check_passed: Mapped[bool | None] = mapped_column(Boolean)

    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)

    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
