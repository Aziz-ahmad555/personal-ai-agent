"""Application status rules — pure, deterministic code; no I/O, no LLM.

Every status on an application was entered by the user; nothing here (or anywhere) infers
one. These rules only decide which moves are *allowed*, so the pipeline stays coherent:

    saved -> applied -> screening -> interviewing -> offer -> accepted
                 \\__________\\____________\\____________\\-> rejected / withdrawn / no_response

- An application must be marked "applied" before it can progress — you can't jump from
  "saved" straight to "offer".
- Once applied, it can move forward to any later stage (skipping "screening" is common), or
  be closed from any active stage.
- A closed application (rejected / withdrawn / no_response) stays closed unless it is
  explicitly reopened into an active stage, which is a distinct, recorded action.
- "accepted" is final.
"""

from datetime import date

ACTIVE_STAGES = ("saved", "applied", "screening", "interviewing", "offer")
CLOSED_STATUSES = ("accepted", "rejected", "withdrawn", "no_response")
REOPENABLE_STATUSES = ("rejected", "withdrawn", "no_response")
REOPEN_TARGETS = ("applied", "screening", "interviewing", "offer")

_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "saved": ("applied", "withdrawn"),
    "applied": ("screening", "interviewing", "offer", "rejected", "withdrawn", "no_response"),
    "screening": ("interviewing", "offer", "rejected", "withdrawn", "no_response"),
    "interviewing": ("offer", "rejected", "withdrawn", "no_response"),
    # An offer can be accepted, or end (the employer rescinded it, or the user declined).
    "offer": ("accepted", "rejected", "withdrawn"),
    "accepted": (),
    "rejected": (),
    "withdrawn": (),
    "no_response": (),
}


class ApplicationTransitionError(ValueError):
    """The requested status change isn't allowed from the current status."""


def forward_transitions(status: str) -> list[str]:
    """Moves available from `status` without reopening anything."""
    return list(_TRANSITIONS.get(status, ()))


def reopen_targets(status: str) -> list[str]:
    """Active stages a closed application can be explicitly reopened into."""
    return list(REOPEN_TARGETS) if status in REOPENABLE_STATUSES else []


def is_reopen(from_status: str, to_status: str) -> bool:
    return from_status in REOPENABLE_STATUSES and to_status in REOPEN_TARGETS


def validate_transition(from_status: str, to_status: str) -> None:
    if from_status == to_status:
        raise ApplicationTransitionError(f"The application is already '{to_status}'.")
    if to_status in _TRANSITIONS.get(from_status, ()) or is_reopen(from_status, to_status):
        return
    if from_status == "accepted":
        raise ApplicationTransitionError("An accepted application is final and can't be changed.")
    if from_status in REOPENABLE_STATUSES:
        raise ApplicationTransitionError(
            f"A '{from_status}' application can only be reopened into: {', '.join(REOPEN_TARGETS)}."
        )
    if from_status == "saved":
        raise ApplicationTransitionError(
            "Mark the application as 'applied' first — it can't skip straight from 'saved' "
            f"to '{to_status}'."
        )
    raise ApplicationTransitionError(
        f"Can't move from '{from_status}' to '{to_status}'. Allowed: "
        f"{', '.join(forward_transitions(from_status)) or 'none'}."
    )


def follow_up_state(next_action_on: date | None, status: str, *, today: date) -> str | None:
    """ "overdue" / "due_today" / "upcoming", or None when there's nothing to act on. A closed
    application never nags — its follow-up is moot."""
    if next_action_on is None or status in CLOSED_STATUSES:
        return None
    if next_action_on < today:
        return "overdue"
    if next_action_on == today:
        return "due_today"
    return "upcoming"
