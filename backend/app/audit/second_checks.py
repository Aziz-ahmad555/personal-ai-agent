"""Registry of independent second-check functions for red-risk actions.

CLAUDE.md: "Red = explicit confirmation + a second independent check." A red action's own code
proposes it via request_approval — if the check that gates its approval came from that same
code, or from the same API request the human's "yes" arrived in, it would be neither "second"
nor "independent." Each entry here is a deterministic re-verification that app.audit.service.
decide_approval runs itself, server-side, at the moment of decision — against the audit log's
own stored evidence/resource — never something the API caller can simply assert.

Register a check by the exact `action` string passed to request_approval, e.g.:

    async def _verify_send_still_matches_profile(db: AsyncSession, log: AuditLog) -> bool:
        ...  # re-fetch the resource, re-check evidence against current ground truth
    SECOND_CHECKS["gmail.send_email"] = _verify_send_still_matches_profile

If a red-risk action has no registered check, decide_approval refuses to approve it at all
(fail-closed, see ApprovalError in app.audit.service) — deliberately, so that shipping a red
action without wiring a real check is loud (every approval attempt fails) rather than silent
(approval just works, unverified).

See app.auth.account_deletion._verify_evidence_still_matches (registered for
"account.delete_all_data") for a real one, rather than the illustrative sketch above.
"""

from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditLog

SecondCheckFn = Callable[[AsyncSession, AuditLog], Awaitable[bool]]

SECOND_CHECKS: dict[str, SecondCheckFn] = {}
