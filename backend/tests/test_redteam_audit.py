"""Red-team Track A, item 5: the audit/approval gate. The TOCTOU race in decide_approval (two
concurrent decisions on one pending row both reading "pending_approval" before either writes)
is fixed in app.audit.service — decide_approval now does one atomic UPDATE...WHERE instead of
SELECT-then-write, so the database's own row lock serializes concurrent callers; only one can
ever match the WHERE clause. True concurrent-request races aren't practical to reproduce
deterministically in a test, so what's tested here is the observable contract that atomicity
guarantees: a row can never be decided twice (see test_deciding_an_already_decided_action_raises
in test_audit_service.py, which already covers this and still passes against the new code).

This pass also found — and, per an explicit user design decision, has now closed — a second
finding: `second_check_passed` used to be a plain boolean in the same decide request the same
caller sends, with nothing independently verifying it. It's fixed by removing the field from
the client-facing API entirely (app.audit.schemas.ApprovalDecision has no such field) and having
decide_approval itself run a registered, independent check (app.audit.second_checks) at decision
time. See tests/test_audit_service.py for the mechanism's unit coverage; this test proves the
attack itself — a caller trying to assert the claim directly — no longer has any effect."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.service import ApprovalError, decide_approval, request_approval
from app.db.models import User


async def _make_user(db: AsyncSession) -> User:
    user = User(email=f"audit-test-{uuid.uuid4()}@example.com", hashed_password="x")
    db.add(user)
    await db.flush()
    return user


async def test_a_caller_can_no_longer_assert_its_own_second_check_passed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """decide_approval no longer accepts a `second_check_passed` argument at all — the
    self-forgery attack this test is named for isn't rejected at runtime, it's structurally
    impossible to express: there's no parameter left to forge. What decides a red row's
    approval now is exclusively the registry in app.audit.second_checks, run server-side."""
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

        with pytest.raises(TypeError):
            await decide_approval(  # type: ignore[call-arg]
                db,
                audit_log_id=pending.id,
                user_id=user.id,
                approved=True,
                second_check_passed=True,
            )

        # And with the forged kwarg gone, the honest call path still refuses to approve —
        # this action has no independent check registered, so it's fail-closed, not open.
        with pytest.raises(ApprovalError, match="No independent second check"):
            await decide_approval(db, audit_log_id=pending.id, user_id=user.id, approved=True)
