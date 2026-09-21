"""ATS-safe plain text — pure code, no I/O.

Applicant-tracking systems parse resumes as text, and a few things reliably trip them: typographic
symbols (em/en dashes, middle dots, curly quotes, bullets), Markdown markup pasted in literally,
and headings that aren't plain words. The normal Markdown export uses some of those on purpose
(it reads well). This renders the same resume as plain ASCII-safe text with standard uppercase
headings, and detects the hazards so the checker can report them.

Accented *letters* are kept (removing them would misspell names like "José"); it's the symbols
that get replaced.
"""

from datetime import date

from app.career.resume_base import ResumeBase

# Replacements for the typographic symbols this system's own exports and user text can contain.
_REPLACEMENTS = {
    "—": "-",
    "–": "-",
    "‒": "-",
    "―": "-",
    "‑": "-",
    "·": "|",
    "•": "-",
    "∙": "-",
    "“": '"',
    "”": '"',
    "„": '"',
    "‘": "'",
    "’": "'",
    "…": "...",
    "\u00a0": " ",  # non-breaking space
    "→": "->",
    "×": "x",
}


def find_hazard_chars(text: str) -> dict[str, int]:
    """Non-ASCII characters that aren't letters (symbols and punctuation), with counts. Accented
    letters are not hazards."""
    found: dict[str, int] = {}
    for char in text:
        if ord(char) > 127 and not char.isalpha():
            found[char] = found.get(char, 0) + 1
    return found


def markdown_marker_count(text: str) -> int:
    """Lines that are Markdown headings ('#', '##', ...) — literal noise in a plain-text parse."""
    return sum(1 for line in text.splitlines() if line.lstrip().startswith("#"))


def to_ascii_safe(text: str) -> str:
    """Replaces typographic symbols with plain equivalents and drops any other non-letter,
    non-ASCII symbol. Letters (including accented ones) are preserved."""
    out: list[str] = []
    for char in text:
        if ord(char) <= 127 or char.isalpha():
            out.append(char)
        else:
            out.append(_REPLACEMENTS.get(char, ""))
    return "".join(out)


def _month_year(iso: str) -> str:
    return date.fromisoformat(iso).strftime("%b %Y")


def _span(start: str | None, end: str | None) -> str:
    if not start:
        return ""
    return f"{_month_year(start)} - {_month_year(end) if end else 'Present'}"


def render_ats_plain(base: ResumeBase) -> str:
    """The resume as plain text: uppercase section headings, no Markdown, ASCII-safe. Contact
    details aren't stored in the profile, so none are invented."""
    lines: list[str] = [base.name or base.headline or "Resume"]
    if base.name and base.headline:
        lines.append(base.headline)
    if base.location:
        lines.append(base.location)

    if (base.summary or "").strip():
        lines += ["", "SUMMARY", (base.summary or "").strip()]

    if base.experiences:
        lines += ["", "EXPERIENCE"]
        for exp in sorted(base.experiences, key=lambda e: e.start, reverse=True):
            lines += ["", f"{exp.title} - {exp.company}"]
            meta = " | ".join(x for x in (_span(exp.start, exp.end), exp.location) if x)
            if meta:
                lines.append(meta)
            if (exp.description or "").strip():
                lines.append((exp.description or "").strip())

    if base.educations:
        lines += ["", "EDUCATION"]
        for edu in base.educations:
            detail = ", ".join(x for x in (edu.degree, edu.field) if x)
            lines += ["", f"{edu.institution}" + (f" - {detail}" if detail else "")]
            span = _span(edu.start, edu.end)
            if span:
                lines.append(span)

    if base.skills:
        lines += ["", "SKILLS", ", ".join(s.name for s in base.skills)]

    return to_ascii_safe("\n".join(lines)) + "\n"
