"""The base resume, assembled from the user's profile, and its rendering — pure code, no I/O.

The base is the single source of truth a tailored resume is checked against: anything a
tailored resume says must trace back to something in here. It holds only what the profile
holds, and only skills with recorded evidence; a skill asserted without evidence is kept
separately (`unevidenced_skills`) so it can be reported as a gap but never written into a
resume.
"""

import hashlib
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Protocol


@dataclass
class ExperienceItem:
    id: str
    company: str
    title: str
    location: str | None
    start: str  # ISO date
    end: str | None  # ISO date; None = current
    description: str | None
    # Names of evidence-backed skills whose evidence points at this role.
    linked_skills: list[str] = field(default_factory=list)


@dataclass
class EducationItem:
    id: str
    institution: str
    degree: str | None
    field: str | None
    start: str | None
    end: str | None


@dataclass
class SkillItem:
    name: str
    level: str
    category: str | None
    # The latest evidence recorded for this skill (what makes it claimable at all).
    evidence: str = ""


@dataclass
class ResumeBase:
    name: str | None
    headline: str | None
    location: str | None
    summary: str | None
    experiences: list[ExperienceItem] = field(default_factory=list)
    educations: list[EducationItem] = field(default_factory=list)
    skills: list[SkillItem] = field(default_factory=list)
    unevidenced_skills: list[str] = field(default_factory=list)

    @property
    def has_tailorable_content(self) -> bool:
        return bool((self.summary or "").strip()) or any(
            (e.description or "").strip() for e in self.experiences
        )

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    def stamp(self) -> str:
        """Hash of everything in the base, so a later profile edit marks a tailored resume stale."""
        payload = json.dumps(self.to_json(), sort_keys=True, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "ResumeBase":
        return cls(
            name=data.get("name"),
            headline=data.get("headline"),
            location=data.get("location"),
            summary=data.get("summary"),
            experiences=[ExperienceItem(**e) for e in data.get("experiences", [])],
            educations=[EducationItem(**e) for e in data.get("educations", [])],
            skills=[SkillItem(**s) for s in data.get("skills", [])],
            unevidenced_skills=list(data.get("unevidenced_skills", [])),
        )

    def all_text(self) -> str:
        """Every word the profile actually contains — what a tailored resume may draw on."""
        parts: list[str] = [self.headline or "", self.location or "", self.summary or ""]
        for exp in self.experiences:
            parts += [exp.company, exp.title, exp.location or "", exp.description or ""]
        for edu in self.educations:
            parts += [edu.institution, edu.degree or "", edu.field or ""]
        parts += [skill.name for skill in self.skills]
        return "\n".join(parts)


class ChangeLike(Protocol):
    change_type: str
    target_id: str
    after_text: str
    decision: str


def apply_accepted(base: ResumeBase, changes: Sequence[ChangeLike]) -> ResumeBase:
    """The base with only the *accepted* changes applied. Pending and rejected changes leave
    the original wording untouched — nothing takes effect until the user says so."""
    result = ResumeBase.from_json(base.to_json())
    for change in changes:
        if change.decision != "accepted":
            continue
        if change.change_type == "rewrite":
            if change.target_id == "summary":
                result.summary = change.after_text
            elif change.target_id.startswith("exp:"):
                exp_id = change.target_id.removeprefix("exp:")
                for exp in result.experiences:
                    if exp.id == exp_id:
                        exp.description = change.after_text
        elif change.change_type == "skills_order":
            wanted = change.after_text.split("\n")
            by_name = {s.name: s for s in result.skills}
            ordered = [by_name[name] for name in wanted if name in by_name]
            ordered += [s for s in result.skills if s.name not in wanted]
            result.skills = ordered
    return result


def _month_year(iso: str) -> str:
    parsed = date.fromisoformat(iso)
    return parsed.strftime("%b %Y")


def _span(start: str | None, end: str | None) -> str:
    if not start:
        return ""
    return f"{_month_year(start)} – {_month_year(end) if end else 'Present'}"


def render_markdown(base: ResumeBase) -> str:
    """Plain Markdown. Contact details aren't stored in the profile, so none are invented —
    the user adds their own before sending it anywhere."""
    lines: list[str] = []
    title = base.name or base.headline or "Resume"
    lines.append(f"# {title}")
    if base.name and base.headline:
        lines.append(base.headline)
    if base.location:
        lines.append(base.location)

    if (base.summary or "").strip():
        lines += ["", "## Summary", (base.summary or "").strip()]

    if base.experiences:
        lines += ["", "## Experience"]
        for exp in sorted(base.experiences, key=lambda e: e.start, reverse=True):
            lines += ["", f"### {exp.title} — {exp.company}"]
            meta = " · ".join(x for x in (_span(exp.start, exp.end), exp.location) if x)
            if meta:
                lines.append(meta)
            if (exp.description or "").strip():
                lines += ["", (exp.description or "").strip()]

    if base.educations:
        lines += ["", "## Education"]
        for edu in base.educations:
            detail = ", ".join(x for x in (edu.degree, edu.field) if x)
            lines += ["", f"### {edu.institution}" + (f" — {detail}" if detail else "")]
            span = _span(edu.start, edu.end)
            if span:
                lines.append(span)

    if base.skills:
        lines += ["", "## Skills", ", ".join(s.name for s in base.skills)]

    return "\n".join(lines) + "\n"
