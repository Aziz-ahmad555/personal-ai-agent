"""Deterministic, evidence-traceable event classification: no LLM, no network. Every result
states which phrase or domain matched, so nothing is ever presented as a guess. When nothing
matches, the event is "other" — never forced into a category it doesn't clearly belong to.
"""

import re
from dataclasses import dataclass
from typing import Literal

EventKind = Literal["interview", "deadline", "other"]

# Phrases, not bare words: something like "due" alone would false-positive on "due to" and
# similar unrelated phrasing. Checked as substrings of the lower-cased title + description.
INTERVIEW_PHRASES = (
    "interview",
    "phone screen",
    "phone screening",
    "on-site",
    "onsite",
    "technical screen",
    "technical interview",
    "coding interview",
    "behavioral interview",
    "hiring manager",
    "panel interview",
    "final round",
    "recruiter call",
    "recruiter chat",
)
DEADLINE_PHRASES = (
    "deadline",
    "application deadline",
    "apply by",
    "apply before",
    "due by",
    "submission deadline",
    "deadline to apply",
    "closing date",
)


def _longest_match(text: str, phrases: tuple[str, ...]) -> str | None:
    """The most specific phrase present, not just the first one in the list — otherwise a
    generic phrase earlier in the tuple (like bare "interview") would always win over a more
    specific one that contains it (like "technical interview")."""
    found = [phrase for phrase in phrases if phrase in text]
    return max(found, key=len) if found else None


def classify_event(summary: str | None, description: str | None) -> tuple[EventKind, str | None]:
    """The kind, and the exact phrase that matched — the evidence a user would want to see
    before trusting the label. Interview phrases are checked first: an event can plausibly
    mention both ("interview - apply by Friday for the next round"), and being invited to an
    interview is the more specific, more actionable fact."""
    text = f"{summary or ''} {description or ''}".lower()
    interview_match = _longest_match(text, INTERVIEW_PHRASES)
    if interview_match:
        return "interview", interview_match
    deadline_match = _longest_match(text, DEADLINE_PHRASES)
    if deadline_match:
        return "deadline", deadline_match
    return "other", None


# Company names shorter than this (after stripping common suffixes) are too generic to match
# safely against free-text titles/descriptions — e.g. a company literally named "Go" or "It".
_MIN_COMPANY_LENGTH = 3
_COMPANY_SUFFIXES = re.compile(
    r"\b(inc|incorporated|llc|ltd|limited|corp|corporation|co|company|gmbh|plc|"
    r"technologies|technology|tech|labs|group|holdings)\.?\b",
    re.IGNORECASE,
)


def _normalize_company(name: str) -> str:
    stripped = _COMPANY_SUFFIXES.sub("", name)
    return re.sub(r"[^a-z0-9]+", " ", stripped.lower()).strip()


@dataclass(frozen=True)
class ApplicationCandidate:
    """The little a match needs to know about one tracked application."""

    application_id: str
    company_name: str | None
    company_domain: str | None


@dataclass(frozen=True)
class ApplicationMatch:
    application_id: str
    reason: str


def _attendee_domains(attendees: list[dict[str, object]], organizer_email: str | None) -> set[str]:
    emails = [str(a.get("email", "")) for a in attendees if a.get("email")]
    if organizer_email:
        emails.append(organizer_email)
    return {email.split("@", 1)[1].lower() for email in emails if "@" in email}


def find_application_match(
    *,
    summary: str | None,
    description: str | None,
    attendees: list[dict[str, object]],
    organizer_email: str | None,
    candidates: list[ApplicationCandidate],
) -> ApplicationMatch | None:
    """Tries an attendee/organizer email domain against each tracked application's employer
    domain first (the stronger signal — a real address, not free text), then a whole-word
    match of the company name in the event's own text. Returns the first hit, or None rather
    than a low-confidence guess."""
    domains = _attendee_domains(attendees, organizer_email)
    for candidate in candidates:
        domain = (candidate.company_domain or "").lower().removeprefix("www.")
        if domain and domain in domains:
            return ApplicationMatch(
                candidate.application_id, f"an attendee's email domain matches {domain}"
            )

    text = f"{summary or ''} {description or ''}"
    for candidate in candidates:
        if not candidate.company_name:
            continue
        normalized = _normalize_company(candidate.company_name)
        if len(normalized) < _MIN_COMPANY_LENGTH:
            continue
        pattern = r"\b" + re.escape(normalized).replace(r"\ ", r"\s+") + r"\b"
        if re.search(pattern, text, re.IGNORECASE):
            return ApplicationMatch(
                candidate.application_id, f"the event mentions {candidate.company_name}"
            )
    return None
