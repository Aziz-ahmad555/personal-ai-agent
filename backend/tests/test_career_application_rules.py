"""Status rules and follow-up state — pure functions, no DB."""

from datetime import date

import pytest

from app.career.application_rules import (
    ACTIVE_STAGES,
    CLOSED_STATUSES,
    ApplicationTransitionError,
    follow_up_state,
    forward_transitions,
    is_reopen,
    reopen_targets,
    validate_transition,
)

ALL_STATUSES = (*ACTIVE_STAGES, *CLOSED_STATUSES)


@pytest.mark.parametrize(
    ("from_status", "to_status"),
    [
        ("saved", "applied"),
        ("saved", "withdrawn"),
        ("applied", "screening"),
        ("applied", "interviewing"),  # skipping screening is common
        ("applied", "offer"),
        ("applied", "no_response"),
        ("screening", "interviewing"),
        ("interviewing", "rejected"),
        ("offer", "accepted"),
        ("offer", "withdrawn"),
    ],
)
def test_allowed_moves(from_status: str, to_status: str) -> None:
    validate_transition(from_status, to_status)  # must not raise


def test_cannot_skip_applied() -> None:
    with pytest.raises(ApplicationTransitionError, match="Mark the application as 'applied'"):
        validate_transition("saved", "offer")
    with pytest.raises(ApplicationTransitionError):
        validate_transition("saved", "interviewing")


def test_cannot_move_backward_through_the_pipeline() -> None:
    with pytest.raises(ApplicationTransitionError):
        validate_transition("interviewing", "screening")
    with pytest.raises(ApplicationTransitionError):
        validate_transition("applied", "saved")


def test_moving_to_the_same_status_is_rejected() -> None:
    with pytest.raises(ApplicationTransitionError, match="already"):
        validate_transition("applied", "applied")


def test_accepted_is_final() -> None:
    for target in ALL_STATUSES:
        if target == "accepted":
            continue
        with pytest.raises(ApplicationTransitionError, match="final"):
            validate_transition("accepted", target)
    assert forward_transitions("accepted") == []
    assert reopen_targets("accepted") == []


@pytest.mark.parametrize("closed", ["rejected", "withdrawn", "no_response"])
def test_closed_applications_can_only_be_explicitly_reopened_into_active_stages(
    closed: str,
) -> None:
    assert forward_transitions(closed) == []
    assert reopen_targets(closed) == ["applied", "screening", "interviewing", "offer"]

    validate_transition(closed, "interviewing")
    assert is_reopen(closed, "interviewing") is True
    with pytest.raises(ApplicationTransitionError, match="reopened"):
        validate_transition(closed, "saved")
    with pytest.raises(ApplicationTransitionError):
        validate_transition(closed, "accepted")


def test_ordinary_moves_are_not_reopens() -> None:
    assert is_reopen("applied", "screening") is False
    assert is_reopen("saved", "applied") is False


def test_every_status_has_a_defined_rule_set() -> None:
    # Guards against adding a status and forgetting its transitions.
    for status in ALL_STATUSES:
        assert isinstance(forward_transitions(status), list)


TODAY = date(2026, 9, 21)


def test_follow_up_states() -> None:
    assert follow_up_state(date(2026, 9, 20), "applied", today=TODAY) == "overdue"
    assert follow_up_state(date(2026, 9, 21), "applied", today=TODAY) == "due_today"
    assert follow_up_state(date(2026, 9, 25), "applied", today=TODAY) == "upcoming"
    assert follow_up_state(None, "applied", today=TODAY) is None


def test_closed_applications_never_show_a_follow_up() -> None:
    for status in CLOSED_STATUSES:
        assert follow_up_state(date(2026, 9, 1), status, today=TODAY) is None
