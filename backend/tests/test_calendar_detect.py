"""Deterministic event classification and application matching: pure functions, no DB, no
network. Every result states what matched, so nothing is presented as a guess."""

from app.calendar.detect import ApplicationCandidate, classify_event, find_application_match

# --- classify_event ---------------------------------------------------------------------


def test_interview_phrases_are_found_in_the_title() -> None:
    kind, reason = classify_event("Technical Interview with Acme", None)

    assert kind == "interview"
    assert reason == "technical interview"


def test_interview_phrases_are_also_found_in_the_description() -> None:
    kind, reason = classify_event("Call", "This will be a phone screen with the hiring team.")

    assert (kind, reason) == ("interview", "phone screen")


def test_deadline_phrases_are_found() -> None:
    assert classify_event("Reminder", "Apply by Friday!") == ("deadline", "apply by")
    assert classify_event("Grad program deadline", None)[0] == "deadline"


def test_case_is_ignored() -> None:
    kind, reason = classify_event("ON-SITE INTERVIEW", None)

    assert kind == "interview"
    assert reason in ("on-site", "interview")  # either is a truthful match; both are present


def test_nothing_matching_is_other_not_a_guess() -> None:
    assert classify_event("Lunch with Sam", "Catching up.") == ("other", None)
    assert classify_event(None, None) == ("other", None)


def test_interview_is_checked_before_deadline_when_both_could_match() -> None:
    kind, reason = classify_event("Interview - apply by Friday for the next round", None)

    assert kind == "interview"
    assert reason == "interview"


def test_a_generic_word_like_due_alone_is_not_a_deadline_keyword() -> None:
    # "due to the weather" must not be mistaken for a deadline.
    assert classify_event("Meeting due to the weather change", None) == ("other", None)


# --- find_application_match: domains -----------------------------------------------------


def _candidate(
    app_id: str = "a1", name: str | None = "Acme Corp", domain: str | None = "example.com"
):
    return ApplicationCandidate(app_id, name, domain)


def test_an_attendee_email_domain_matches_the_tracked_employer() -> None:
    match = find_application_match(
        summary="Chat",
        description=None,
        attendees=[{"email": "person-02@example.com"}],
        organizer_email=None,
        candidates=[_candidate()],
    )

    assert match is not None
    assert match.application_id == "a1"
    assert "example.com" in match.reason


def test_the_organizer_email_domain_also_counts() -> None:
    match = find_application_match(
        summary="Chat",
        description=None,
        attendees=[],
        organizer_email="person-03@example.com",
        candidates=[_candidate()],
    )

    assert match is not None and match.application_id == "a1"


def test_an_unrelated_domain_does_not_match() -> None:
    match = find_application_match(
        summary="Chat",
        description=None,
        attendees=[{"email": "person-04@example.com"}],
        organizer_email=None,
        candidates=[_candidate(domain="unrelated-company.example")],
    )

    assert match is None


def test_a_candidate_with_no_domain_is_skipped_for_domain_matching() -> None:
    match = find_application_match(
        summary="Chat with Acme Corp",
        description=None,
        attendees=[{"email": "person-04@example.com"}],
        organizer_email=None,
        candidates=[_candidate(domain=None)],
    )

    # Falls through to the name match instead.
    assert match is not None
    assert "mentions Acme Corp" in match.reason


# --- find_application_match: company name in text -----------------------------------------


def test_the_company_name_is_matched_in_the_event_text() -> None:
    match = find_application_match(
        summary="Interview with Acme Corp",
        description=None,
        attendees=[],
        organizer_email=None,
        candidates=[_candidate(domain=None)],
    )

    assert match is not None and match.application_id == "a1"


def test_the_match_is_whole_word_not_a_substring_inside_another_word() -> None:
    # "Acme" must not match inside "Acmeville" or similar.
    match = find_application_match(
        summary="Meeting in Acmeville",
        description=None,
        attendees=[],
        organizer_email=None,
        candidates=[ApplicationCandidate("a1", "Acme", None)],
    )

    assert match is None


def test_company_suffixes_are_stripped_before_matching() -> None:
    match = find_application_match(
        summary="Call with Acme",  # the tracked name has "Corp" but the event doesn't say it
        description=None,
        attendees=[],
        organizer_email=None,
        candidates=[_candidate(name="Acme Corp", domain=None)],
    )

    assert match is not None


def test_a_very_short_or_generic_company_name_is_not_matched_by_text() -> None:
    # A company named "Go" or "It" would otherwise match almost anything.
    match = find_application_match(
        summary="Go get coffee",
        description=None,
        attendees=[],
        organizer_email=None,
        candidates=[ApplicationCandidate("a1", "Go", None)],
    )

    assert match is None


def test_no_candidates_or_no_signal_at_all_is_none() -> None:
    assert (
        find_application_match(
            summary="Lunch", description=None, attendees=[], organizer_email=None, candidates=[]
        )
        is None
    )
    assert (
        find_application_match(
            summary="Lunch",
            description=None,
            attendees=[],
            organizer_email=None,
            candidates=[_candidate()],
        )
        is None
    )


def test_domain_matches_are_preferred_over_name_matches() -> None:
    # Two candidates; only the domain-matching one should win even though both names appear.
    candidates = [
        ApplicationCandidate("wrong", "Acme Corp", "notacme.example"),
        ApplicationCandidate("right", "Acme Corp", "example.com"),
    ]
    match = find_application_match(
        summary="Interview with Acme Corp",
        description=None,
        attendees=[{"email": "person-02@example.com"}],
        organizer_email=None,
        candidates=candidates,
    )

    assert match is not None and match.application_id == "right"
