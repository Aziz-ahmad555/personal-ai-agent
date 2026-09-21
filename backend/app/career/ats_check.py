"""ATS compatibility checks — pure, deterministic code; no LLM, no I/O.

No applicant-tracking vendor publishes how it scores resumes, so this doesn't pretend to predict
a specific employer's ranking. It checks two things that are well documented and computable:

- **Keyword coverage** — do the skills the posting asks for (the same quote-verified
  requirements the match uses) actually appear in the resume text, and where? A skill used in
  context (in a summary or a role) counts for more than one that only sits in a Skills list.
- **Parsing hygiene** — standard section headings, contact details, parseable and ordered dates,
  a sensible length, and characters that commonly trip parsers.

Nothing here edits a resume. It only reports, and a skill you have no evidence for is reported
as a gap — never as something to "add".
"""

import re
from dataclasses import dataclass, field
from typing import Literal

from app.career.ats_render import find_hazard_chars, markdown_marker_count
from app.career.matching import normalize_skill
from app.career.resume_base import ResumeBase
from app.career.resume_verify import mentions_term

KeywordState = Literal["in_context", "listed_only", "gap"]
CheckStatus = Literal["pass", "warn", "fail"]

HEADING_ALIASES: dict[str, set[str]] = {
    "summary": {"summary", "professional summary", "profile", "objective", "about"},
    "experience": {
        "experience",
        "work experience",
        "professional experience",
        "employment history",
        "work history",
    },
    "education": {"education", "academic background"},
    "skills": {"skills", "technical skills", "core competencies"},
}
_ALIAS_TO_KEY = {alias: key for key, aliases in HEADING_ALIASES.items() for alias in aliases}

MIN_WORDS = 150
MAX_WORDS = 1100

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d[\s().-]{0,2}){9,14}\d(?!\d)")
_ONLY_YEARS_RE = re.compile(r"(?:(?:19|20)\d{2})+")
_MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?"
_DATE_RANGE_RE = re.compile(
    rf"(?:(?P<sm>{_MONTH})\s+)?(?P<sy>(?:19|20)\d{{2}})\s*(?:-|–|—|to)\s*"
    rf"(?:(?P<em>{_MONTH})\s+)?(?P<ey>(?:19|20)\d{{2}}|Present|Current|Now)",
    re.IGNORECASE,
)
_MONTH_NUMBERS = {
    m: i for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1
    )
}


@dataclass
class KeywordResult:
    name: str
    kind: Literal["required", "preferred"]
    state: KeywordState
    detail: str
    # For a skill that's only in the Skills list: the roles whose evidence points at it — where
    # it could honestly be shown in context.
    roles: list[str] = field(default_factory=list)


@dataclass
class KeywordStats:
    required_found: int
    required_total: int
    preferred_found: int
    preferred_total: int
    in_context: int
    # Share of all requested skills found anywhere (in context or listed); None if none requested.
    coverage_percent: int | None


@dataclass
class Check:
    key: str
    label: str
    status: CheckStatus
    detail: str


@dataclass
class Section:
    key: str | None  # summary / experience / education / skills, or None for anything else
    heading: str
    body: str


def _heading_key(line: str) -> tuple[str | None, bool]:
    """(section key, whether this line is a heading at all). A line is a heading if it's a
    Markdown '#' heading, or a short standalone line that is a known section name."""
    stripped = line.strip()
    if not stripped:
        return None, False
    is_markdown = stripped.startswith("#")
    name = stripped.lstrip("#").strip().rstrip(":").lower()
    if name in _ALIAS_TO_KEY and (is_markdown or len(name.split()) <= 3):
        return _ALIAS_TO_KEY[name], True
    return None, is_markdown and stripped.startswith("##") and not stripped.startswith("###")


def split_sections(text: str) -> list[Section]:
    """Splits into sections at recognized headings (and any other '##' heading, which is kept as
    an unrecognized section). Text before the first heading is the "header" (name, headline...)."""
    sections: list[Section] = [Section(None, "", "")]
    for line in text.splitlines():
        key, is_heading = _heading_key(line)
        if is_heading:
            sections.append(Section(key, line.strip().lstrip("#").strip(), ""))
        else:
            sections[-1].body += line + "\n"
    return sections


def _bodies(sections: list[Section], keys: set[str | None]) -> str:
    return "\n".join(s.body for s in sections if s.key in keys)


def check_keywords(
    text: str, requirements: list[dict[str, str]], base: ResumeBase
) -> tuple[list[KeywordResult], KeywordStats]:
    sections = split_sections(text)
    recognized = {s.key for s in sections if s.key}
    if recognized:
        context = _bodies(sections, {None, "summary", "experience", "education"})
        skills_text = _bodies(sections, {"skills"})
    else:  # no structure to speak of: any mention is as good as it gets
        context, skills_text = text, ""

    evidenced = {normalize_skill(s.name) for s in base.skills}
    unevidenced = {normalize_skill(n) for n in base.unevidenced_skills}

    results: list[KeywordResult] = []
    seen: set[str] = set()
    for req in requirements:
        name = req["name"]
        kind: Literal["required", "preferred"] = (
            "preferred" if req["kind"] == "preferred" else "required"
        )
        norm = normalize_skill(name)
        if norm in seen:
            continue
        seen.add(norm)
        linked = [
            f"{e.title} — {e.company}"
            for e in base.experiences
            if norm in {normalize_skill(s) for s in e.linked_skills}
        ]
        if mentions_term(context, name):
            results.append(
                KeywordResult(
                    name,
                    kind,
                    "in_context",
                    "Used in your summary or a role — the strongest place for it.",
                )
            )
        elif mentions_term(skills_text, name):
            where = (
                f" Your evidence links it to: {', '.join(linked)}."
                if linked
                else " If it's true of a specific role, say so there."
            )
            results.append(
                KeywordResult(
                    name,
                    kind,
                    "listed_only",
                    "Only in your Skills list. Keyword matching will find it, but it carries more "
                    "weight when shown in use." + where,
                    linked,
                )
            )
        else:
            if norm in evidenced:
                reason = "You have evidence for it, but it isn't in this resume's text."
            elif norm in unevidenced:
                reason = "It's in your profile with no evidence recorded, so it isn't listed."
            else:
                reason = "It isn't in your profile, so it isn't on your resume."
            results.append(KeywordResult(name, kind, "gap", reason))

    def found(kind: str) -> int:
        return sum(1 for r in results if r.kind == kind and r.state != "gap")

    def total(kind: str) -> int:
        return sum(1 for r in results if r.kind == kind)

    all_found = sum(1 for r in results if r.state != "gap")
    stats = KeywordStats(
        required_found=found("required"),
        required_total=total("required"),
        preferred_found=found("preferred"),
        preferred_total=total("preferred"),
        in_context=sum(1 for r in results if r.state == "in_context"),
        coverage_percent=round(100 * all_found / len(results)) if results else None,
    )
    return results, stats


def _has_phone(text: str) -> bool:
    """A phone-number-shaped run of digits — but not a string of years like "2019 2020 2021"."""
    for match in _PHONE_RE.finditer(text):
        digits = re.sub(r"\D", "", match.group())
        if not _ONLY_YEARS_RE.fullmatch(digits):
            return True
    return False


def _start_value(match: re.Match[str]) -> int:
    month = _MONTH_NUMBERS.get((match.group("sm") or "")[:3].lower(), 0)
    return int(match.group("sy")) * 12 + month


def check_structure(text: str) -> list[Check]:
    sections = split_sections(text)
    checks: list[Check] = []

    # --- section headings ---
    present = {s.key for s in sections if s.key}
    unrecognized = [s.heading for s in sections if s.key is None and s.heading]
    missing_bits: list[str] = []
    status: CheckStatus = "pass"
    if "experience" not in present:
        status = "fail"
        missing_bits.append("no Experience section")
    for key, label in (("skills", "Skills"), ("education", "Education")):
        if key not in present:
            status = "fail" if status == "fail" else "warn"
            missing_bits.append(f"no {label} section")
    if unrecognized:
        status = "fail" if status == "fail" else "warn"
        missing_bits.append(f"non-standard heading(s): {', '.join(unrecognized)}")
    checks.append(
        Check(
            "sections",
            "Section headings",
            status,
            "Standard headings found: " + ", ".join(k.title() for k in sorted(present)) + "."
            if status == "pass"
            else "Problems: " + "; ".join(missing_bits) + ". ATS systems look for standard "
            "headings such as Experience, Education, and Skills to find each part of a resume.",
        )
    )

    # --- contact details ---
    has_email = bool(_EMAIL_RE.search(text))
    has_phone = _has_phone(text)
    if has_email and has_phone:
        contact = Check("contact", "Contact details", "pass", "Email and phone number found.")
    elif has_email or has_phone:
        contact = Check(
            "contact",
            "Contact details",
            "warn",
            (
                "Only an email found — add a phone number too."
                if has_email
                else "Only a phone number found — add an email address too."
            ),
        )
    else:
        contact = Check(
            "contact",
            "Contact details",
            "fail",
            "No email or phone number found. Your profile doesn't store contact details, so add "
            "your own to the top of the resume before sending it — an ATS can't reach you without "
            "them.",
        )
    checks.append(contact)

    # --- dates (only meaningful if there is an experience section) ---
    if "experience" in present:
        experience = _bodies(sections, {"experience"})
        ranges = list(_DATE_RANGE_RE.finditer(experience))
        if not ranges:
            checks.append(
                Check(
                    "dates",
                    "Employment dates",
                    "warn",
                    "No date ranges found in your experience. ATS systems use them to work out "
                    "tenure and recency; write them as 'Mar 2024 - Present'.",
                )
            )
        else:
            styles = {"month" if r.group("sm") else "year" for r in ranges}
            if len(styles) > 1:
                checks.append(
                    Check(
                        "dates",
                        "Employment dates",
                        "warn",
                        "Dates mix 'Mar 2024' and bare-year styles. Use one format throughout so "
                        "they parse consistently.",
                    )
                )
            else:
                checks.append(
                    Check(
                        "dates",
                        "Employment dates",
                        "pass",
                        f"{len(ranges)} date range(s) found, in one consistent format.",
                    )
                )
            starts = [_start_value(r) for r in ranges]
            newest_first = all(a >= b for a, b in zip(starts, starts[1:], strict=False))
            checks.append(
                Check(
                    "order",
                    "Newest role first",
                    "pass" if newest_first else "warn",
                    "Roles run from newest to oldest."
                    if newest_first
                    else "Roles aren't in reverse-chronological order, which is what ATS "
                    "systems and recruiters expect.",
                )
            )

    # --- length ---
    words = len(text.split())
    if words < MIN_WORDS:
        checks.append(
            Check(
                "length",
                "Length",
                "warn",
                f"{words} words is very short — there's little for a system to match. Add "
                "detail to your summary and role descriptions.",
            )
        )
    elif words > MAX_WORDS:
        checks.append(
            Check(
                "length",
                "Length",
                "warn",
                f"{words} words is long. Most resumes are best kept to one or two pages.",
            )
        )
    else:
        checks.append(Check("length", "Length", "pass", f"{words} words — a sensible length."))

    # --- parsing hazards ---
    hazards = find_hazard_chars(text)
    markers = markdown_marker_count(text)
    if hazards or markers:
        parts: list[str] = []
        if hazards:
            ranked = sorted(hazards.items(), key=lambda kv: -kv[1])
            shown = ", ".join(f"{c} ×{n}" for c, n in ranked)
            parts.append(f"special symbols ({shown})")
        if markers:
            parts.append(f"{markers} Markdown heading marker(s) ('#')")
        checks.append(
            Check(
                "hazards",
                "Characters that can trip parsers",
                "warn",
                "Contains " + " and ".join(parts) + ". Some parsers drop or garble these. The "
                "ATS-safe version replaces them with plain equivalents.",
            )
        )
    else:
        checks.append(
            Check(
                "hazards",
                "Characters that can trip parsers",
                "pass",
                "Plain characters and headings only.",
            )
        )

    return checks


def summarize(checks: list[Check]) -> dict[str, int]:
    return {s: sum(1 for c in checks if c.status == s) for s in ("pass", "warn", "fail")}
