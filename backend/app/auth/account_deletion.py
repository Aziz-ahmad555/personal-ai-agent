"""Full-account "delete all my data" — the genuine version CLAUDE.md's gap survey asked
for, distinct from each integration's own disconnect-and-purge (app.gmail/calendar/github's
own `/connection` DELETE endpoints), which only ever clear that one integration's own data.

Two steps, through the same request/decide machinery every other red-risk action uses
(app.audit.service):

1. request_account_deletion gathers a live snapshot of everything the account owns —
   row counts across every table with a direct `users.id` foreign key, plus which
   integrations are connected — and files it as a pending red-risk approval. The frontend
   renders that snapshot as the confirmation screen, so "are you sure?" shows real numbers,
   not a generic warning.
2. decide_and_execute_account_deletion is the user's second, explicit confirmation.
   Approving it re-derives that same snapshot from the database right now (see
   _verify_evidence_still_matches below, registered into app.audit.second_checks for this
   action) and refuses if it's drifted since step 1 — e.g. a feed poll added new postings
   in between — forcing a fresh request rather than deleting against stale evidence. Only
   if that passes does it revoke every connected integration at its provider, then delete
   the user row itself, which cascades every table in the schema carrying a users.id
   foreign key (every one of them is `ondelete="CASCADE"` — see the alembic migrations).

What doesn't survive this: the account's own audit trail. AuditLog.user_id is itself
`ondelete="CASCADE"` (by design — an audit log belongs to the account, like everything
else), so the very row recording this deletion's approval is deleted along with it, a few
statements later, as an unavoidable consequence of "ALL my data" actually meaning all of
it. The one durable trace of a completed deletion is the structlog line this module writes
right before the delete — outside Postgres, in the app's own log output, deliberately the
one place a "this account existed, then was deleted" fact can outlive the account itself.
"""

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditLog
from app.audit.second_checks import SECOND_CHECKS
from app.audit.service import decide_approval, request_approval
from app.calendar import oauth as calendar_oauth
from app.calendar.models import CalendarConnection
from app.career.models import (
    Application,
    CoverLetter,
    JobBoardFeed,
    JobPosting,
    PracticeSession,
    TailoredResume,
)
from app.db.models import User
from app.github import oauth as github_oauth
from app.github.models import GithubConnection
from app.gmail import oauth as gmail_oauth
from app.gmail.crypto import decrypt_token
from app.gmail.models import GmailConnection
from app.logging import get_logger
from app.profile.models import Preferences, Profile
from app.reporting.models import WeeklyDigest
from app.research.models import ResearchQuery

logger = get_logger(__name__)

ACTION = "account.delete_all_data"

# Every table with a direct `users.id` foreign key (see each model's own ondelete="CASCADE"
# FK) — the same set the alembic migrations enforce in Postgres. Kept as one explicit list
# so the evidence snapshot, the second check, and a human reading this code all see the same
# ground truth; add a model here whenever a new one gains a direct user_id column.
#
# audit_logs is deliberately excluded: it's the one table this very action itself writes to
# (request_account_deletion inserts the pending-approval row being evidenced), so counting it
# would make the snapshot go stale the instant it's taken — a self-inflicted drift the second
# check would then always refuse. It's still deleted via the same cascade as everything else;
# it's just not part of what gets compared for drift.
_OWNED_TABLES: tuple[tuple[str, Any], ...] = (
    ("profile", Profile),
    ("preferences", Preferences),
    ("research_queries", ResearchQuery),
    ("job_postings", JobPosting),
    ("job_board_feeds", JobBoardFeed),
    ("applications", Application),
    ("tailored_resumes", TailoredResume),
    ("cover_letters", CoverLetter),
    ("practice_sessions", PracticeSession),
    ("weekly_digests", WeeklyDigest),
    ("gmail_connection", GmailConnection),
    ("calendar_connection", CalendarConnection),
    ("github_connection", GithubConnection),
)


async def _row_counts(db: AsyncSession, user_id: uuid.UUID) -> dict[str, int]:
    counts: dict[str, int] = {}
    for label, model in _OWNED_TABLES:
        total = await db.scalar(
            select(func.count()).select_from(model).where(model.user_id == user_id)
        )
        counts[label] = int(total or 0)
    return counts


async def _connection_status(db: AsyncSession, user_id: uuid.UUID) -> dict[str, str]:
    gmail = (
        await db.execute(select(GmailConnection).where(GmailConnection.user_id == user_id))
    ).scalar_one_or_none()
    calendar = (
        await db.execute(select(CalendarConnection).where(CalendarConnection.user_id == user_id))
    ).scalar_one_or_none()
    github = (
        await db.execute(select(GithubConnection).where(GithubConnection.user_id == user_id))
    ).scalar_one_or_none()
    return {
        "gmail": gmail.status if gmail else "not_connected",
        "calendar": calendar.status if calendar else "not_connected",
        "github": github.status if github else "not_connected",
    }


async def gather_deletion_evidence(db: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    """A live snapshot of everything this account owns, used both as the evidence shown at
    request time and, re-derived fresh, as the independent check at decide time."""
    return {
        "row_counts": await _row_counts(db, user_id),
        "connections": await _connection_status(db, user_id),
    }


async def request_account_deletion(db: AsyncSession, *, user: User) -> AuditLog:
    evidence = await gather_deletion_evidence(db, user.id)
    total_rows = sum(evidence["row_counts"].values())
    return await request_approval(
        db,
        user_id=user.id,
        action=ACTION,
        risk_level="red",
        summary=(
            f"Permanently delete every record owned by {user.email} ({total_rows} rows "
            "across the account) and revoke every connected integration at its provider. "
            "This cannot be undone."
        ),
        evidence=evidence,
        resource_type="user",
        resource_id=user.id,
    )


async def _verify_evidence_still_matches(db: AsyncSession, log: AuditLog) -> bool:
    """The independent second check for ACTION (registered below): re-derives the account's
    row counts and connection statuses right now and refuses the approval if anything has
    changed since the request was filed — e.g. a scheduled feed poll or sync added rows in
    the meantime — rather than deleting against evidence the user never actually saw."""
    if log.evidence is None:
        return False
    current = await gather_deletion_evidence(db, log.user_id)
    return current == log.evidence


SECOND_CHECKS[ACTION] = _verify_evidence_still_matches


async def _revoke_connected_integrations(db: AsyncSession, user_id: uuid.UUID) -> dict[str, bool]:
    """Best-effort: tells each connected provider to invalidate its grant before the local
    rows (including the connection's own encrypted tokens) are deleted. A provider that can't
    be reached, or a token that can't be decrypted, must never block the rest of the
    deletion — this app's own database is what "delete all my data" is actually about."""
    revoked: dict[str, bool] = {}

    gmail = (
        await db.execute(select(GmailConnection).where(GmailConnection.user_id == user_id))
    ).scalar_one_or_none()
    gmail_token = gmail and (gmail.refresh_token_encrypted or gmail.access_token_encrypted)
    if gmail_token:
        try:
            revoked["gmail"] = await gmail_oauth.revoke_token(decrypt_token(gmail_token))
        except Exception:  # noqa: BLE001 — an unreachable provider must not block deletion
            revoked["gmail"] = False

    calendar = (
        await db.execute(select(CalendarConnection).where(CalendarConnection.user_id == user_id))
    ).scalar_one_or_none()
    calendar_token = calendar and calendar.access_token_encrypted
    if calendar_token:
        try:
            revoked["calendar"] = await calendar_oauth.revoke_token(decrypt_token(calendar_token))
        except Exception:  # noqa: BLE001
            revoked["calendar"] = False

    github = (
        await db.execute(select(GithubConnection).where(GithubConnection.user_id == user_id))
    ).scalar_one_or_none()
    github_token = github and github.access_token_encrypted
    if github_token:
        try:
            revoked["github"] = await github_oauth.revoke_token(decrypt_token(github_token))
        except Exception:  # noqa: BLE001
            revoked["github"] = False

    return revoked


async def decide_and_execute_account_deletion(
    db: AsyncSession, *, audit_log_id: uuid.UUID, user: User, approved: bool
) -> dict[str, Any]:
    """The user's second, explicit confirmation. A decline just records the decision and
    leaves the account untouched. An approval runs the independent second check (via
    decide_approval, which raises ApprovalError and touches nothing if it fails), then
    actually performs the deletion in this same call — there is no further step after
    approval, since leaving "approved but not yet executed" as a resumable state would be
    its own risk for an action this irreversible."""
    log = await decide_approval(db, audit_log_id=audit_log_id, user_id=user.id, approved=approved)
    if not approved:
        await db.commit()
        return {"deleted": False}

    revoked = await _revoke_connected_integrations(db, user.id)
    row_counts = log.evidence["row_counts"] if log.evidence else {}
    logger.warning(
        "account_deleted",
        user_id=str(user.id),
        email=user.email,
        row_counts=row_counts,
        revoked_at_provider=revoked,
    )
    await db.delete(user)
    await db.commit()
    return {"deleted": True, "row_counts": row_counts, "revoked_at_provider": revoked}
