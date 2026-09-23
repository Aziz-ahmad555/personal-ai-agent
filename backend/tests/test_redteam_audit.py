"""Red-team Track A, item 5: the audit/approval gate. The TOCTOU race in decide_approval (two
concurrent decisions on one pending row both reading "pending_approval" before either writes)
is fixed in app.audit.service — decide_approval now does one atomic UPDATE...WHERE instead of
SELECT-then-write, so the database's own row lock serializes concurrent callers; only one can
ever match the WHERE clause. True concurrent-request races aren't practical to reproduce
deterministically in a test, so what's tested here is the observable contract that atomicity
guarantees: a row can never be decided twice (see test_deciding_an_already_decided_action_raises
in test_audit_service.py, which already covers this and still passes against the new code).

What's new here is a real, still-open finding this pass surfaced: `second_check_passed` is a
plain field in the same request the same caller sends — nothing independently verifies it."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.service import decide_approval, request_approval
from app.db.models import User


async def _make_user(db: AsyncSession) -> User:
    user = User(email=f"audit-test-{uuid.uuid4()}@example.com", hashed_password="x")
    db.add(user)
    await db.flush()
    return user


async def test_FINDING_second_check_passed_is_self_forgeable(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Documented gap, not fixed here (flagged to the user as a design-decision item: what a
    genuine independent second check should even consist of is a real design question, not a
    bug with an obvious fix). The docstring on AuditLog.second_check_passed says it should be
    "set by a check that is not the same code path that proposed the action" — but the same
    caller who requested a red-risk action can simply supply
    {"approved": true, "second_check_passed": true} in the exact same decide request, and
    decide_approval has no independent mechanism to verify that claim. Currently latent: no
    `request_approval` call site in the app uses risk_level="red" yet (both real callers, in
    app.github.proposals, use "yellow"), so nothing exploits this today — but the audit API
    itself would honor it the moment a red-risk feature ships without a real second-check
    mechanism behind it."""
    async with session_factory() as db:
        user = await _make_user(db)
        pending = await request_approval(
            db,
            user_id=user.id,
            action="hypothetical.destructive_action",
            risk_level="red",
            summary="A red-risk action, proposed and decided by the same caller.",
        )
        await db.commit()

        # The same user, in one call, supplies both the approval and the "second check" —
        # nothing else in the system independently computed second_check_passed.
        approved = await decide_approval(
            db,
            audit_log_id=pending.id,
            user_id=user.id,
            approved=True,
            second_check_passed=True,
        )
        await db.commit()

    # Today's actual behavior: this succeeds. Recorded here as a known, reported gap — not
    # asserted as correct. If a real second-check mechanism is added, this test should be
    # rewritten to prove a *self-supplied* claim is rejected, not just that the flag exists.
    assert approved.status == "approved"
    assert approved.second_check_passed is True
