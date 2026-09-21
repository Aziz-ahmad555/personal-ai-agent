"""Turns synced repo facts into skill-evidence proposals, and into the reasons other things were
not proposed. Pure functions over plain data: the same repos always give the same result, and
nothing here writes to the profile or touches the network."""

import hashlib
import json
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from app.career.matching import normalize_skill
from app.github.catalog import (
    LANGUAGE_SKILLS,
    MIN_LANGUAGE_BYTES,
    NOTEBOOK_LANGUAGE,
    ROOT_FILE_SKILLS,
)

Via = Literal["language", "dependency", "file"]
Attribution = Literal["attributed", "ownership_only", "unknown"]
Kind = Literal["language", "framework", "tool"]


@dataclass(frozen=True)
class DependencyFact:
    skill: str
    file: str
    url: str


@dataclass(frozen=True)
class RepoFacts:
    name: str
    full_name: str
    html_url: str
    is_fork: bool
    is_archived: bool
    languages: dict[str, int]
    # None means it couldn't be looked up, which is different from 0 (looked up, none found).
    authored_commits: int | None
    last_commit_at: str | None
    root_files: list[str]
    dependencies: list[DependencyFact]
    details_fetched: bool = True


@dataclass(frozen=True)
class ExistingSkill:
    name: str
    latest_level: str | None


@dataclass(frozen=True)
class Contribution:
    repo: str
    repo_url: str
    via: Via
    # The evidence's own address: the manifest or file for dependencies, else the repo.
    source_url: str
    source_file: str | None
    bytes: int | None
    commits: int | None
    last_commit_at: str | None
    attribution: Attribution


@dataclass(frozen=True)
class ProposalDraft:
    skill_name: str
    kind: Kind
    contributions: list[Contribution]
    fingerprint: str
    attribution: Attribution
    existing_skill_name: str | None
    existing_level: str | None


@dataclass(frozen=True)
class Skipped:
    subject: str
    reason: str


@dataclass
class Derivation:
    proposals: list[ProposalDraft] = field(default_factory=list)
    skipped: list[Skipped] = field(default_factory=list)


def _attribution(commits: int | None) -> Attribution:
    if commits is None:
        return "unknown"
    return "attributed" if commits > 0 else "ownership_only"


def _kb(size: int) -> str:
    return f"{size / 1000:.1f} KB"


def fingerprint(contributions: list[Contribution]) -> str:
    """Identifies which evidence a proposal stands on: the repos, how each one shows the skill,
    and whether commits are attributed. Deliberately not the byte or commit counts, so ordinary
    growth of a repo doesn't re-open a proposal the user already decided."""
    key = sorted((c.repo, c.via, c.source_file or "", c.attribution) for c in contributions)
    return hashlib.sha256(json.dumps(key).encode()).hexdigest()[:32]


def derive(repos: list[RepoFacts], existing: dict[str, ExistingSkill]) -> Derivation:
    """`existing` maps normalized skill name -> the user's current profile skill."""
    result = Derivation()
    grouped: dict[str, list[Contribution]] = defaultdict(list)
    kinds: dict[str, Kind] = {}

    def add(skill: str, kind: Kind, contribution: Contribution) -> None:
        grouped[skill].append(contribution)
        # A skill shown both ways (Python as a language, FastAPI as a dependency) keeps the
        # first kind seen; languages are processed first.
        kinds.setdefault(skill, kind)

    for repo in sorted(repos, key=lambda r: r.full_name):
        if repo.is_fork:
            result.skipped.append(
                Skipped(repo.name, "A fork of someone else's project, so not counted as your work.")
            )
            continue
        if repo.is_archived:
            result.skipped.append(
                Skipped(repo.name, "Archived, so not counted as current evidence.")
            )
            continue
        if not repo.details_fetched:
            result.skipped.append(
                Skipped(
                    repo.name,
                    "Its details couldn't be fetched, so nothing is proposed from it yet.",
                )
            )
            continue

        attribution = _attribution(repo.authored_commits)

        def contribution(
            via: Via,
            *,
            source_url: str,
            source_file: str | None = None,
            size: int | None = None,
            repo: RepoFacts = repo,
            attribution: Attribution = attribution,
        ) -> Contribution:
            return Contribution(
                repo=repo.name,
                repo_url=repo.html_url,
                via=via,
                source_url=source_url,
                source_file=source_file,
                bytes=size,
                commits=repo.authored_commits,
                last_commit_at=repo.last_commit_at,
                attribution=attribution,
            )

        languages = repo.languages
        if NOTEBOOK_LANGUAGE in languages and "Python" in languages:
            result.skipped.append(
                Skipped(
                    f"{repo.name}: {NOTEBOOK_LANGUAGE}",
                    "Notebook size (mostly JSON and saved outputs) isn't counted as Python.",
                )
            )
        for language, size in sorted(languages.items(), key=lambda item: -item[1]):
            skill = LANGUAGE_SKILLS.get(language)
            if skill is None:
                result.skipped.append(
                    Skipped(
                        f"{repo.name}: {language}",
                        "A file type GitHub reports, not a skill on its own.",
                    )
                )
            elif size < MIN_LANGUAGE_BYTES:
                result.skipped.append(
                    Skipped(
                        f"{repo.name}: {language}",
                        f"Only {_kb(size)}, under the {_kb(MIN_LANGUAGE_BYTES)} needed to count "
                        "as evidence.",
                    )
                )
            else:
                add(
                    skill, "language", contribution("language", source_url=repo.html_url, size=size)
                )

        for dependency in repo.dependencies:
            add(
                dependency.skill,
                "framework",
                contribution(
                    "dependency",
                    source_url=dependency.url,
                    source_file=dependency.file,
                ),
            )

        for filename in repo.root_files:
            skill = ROOT_FILE_SKILLS.get(filename.lower())
            if skill:
                add(
                    skill,
                    "tool",
                    contribution(
                        "file",
                        source_url=f"{repo.html_url}/blob/HEAD/{filename}",
                        source_file=filename,
                    ),
                )

    for skill, contributions in grouped.items():
        # One repo can show a skill twice (Docker via Dockerfile and compose): keep each file.
        current = existing.get(normalize_skill(skill))
        if any(c.attribution == "attributed" for c in contributions):
            overall: Attribution = "attributed"
        elif any(c.attribution == "unknown" for c in contributions):
            overall = "unknown"
        else:
            overall = "ownership_only"
        result.proposals.append(
            ProposalDraft(
                skill_name=current.name if current else skill,
                kind=kinds[skill],
                contributions=contributions,
                fingerprint=fingerprint(contributions),
                attribution=overall,
                existing_skill_name=current.name if current else None,
                existing_level=current.latest_level if current else None,
            )
        )

    order = {"attributed": 0, "unknown": 1, "ownership_only": 2}
    result.proposals.sort(
        key=lambda p: (
            order[p.attribution],
            -sum(c.commits or 0 for c in p.contributions),
            p.skill_name.lower(),
        )
    )
    return result


def evidence_text(
    login: str, draft_skill: str, contributions: list[Contribution], *, limit: int = 3900
) -> str:
    """The exact sentence that would be saved as the skill's evidence if the user accepts.
    Built only from the recorded facts, so it can be shown before anything is written. Very long
    lists are cut at whole repositories and say how many were left out."""
    parts: list[str] = []
    for c in contributions:
        if c.via == "language":
            what = f"{_kb(c.bytes or 0)} of {draft_skill}"
        elif c.via == "dependency":
            what = f"declared in {c.source_file}"
        else:
            what = f"has a {c.source_file}"
        if c.attribution == "attributed":
            last = f", last {c.last_commit_at[:10]}" if c.last_commit_at else ""
            noun = "commit" if c.commits == 1 else "commits"
            who = f"{c.commits} {noun} by this account{last}"
        elif c.attribution == "ownership_only":
            who = "owned by this account; no commits attributed to it"
        else:
            who = "commit attribution unavailable"
        parts.append(f"{c.repo} ({what}; {who})")

    head = f"GitHub (@{login}): {draft_skill} — "
    text = head + "; ".join(parts) + "."
    kept = len(parts)
    while len(text) > limit and kept > 1:
        kept -= 1
        text = head + "; ".join(parts[:kept]) + f"; and {len(parts) - kept} more."
    return text


def summarize_events(
    events: list[dict[str, Any]], *, now: datetime | None = None
) -> dict[str, Any]:
    """A light picture of recent public activity. GitHub only keeps roughly the last 90 days of
    public events (and at most 300), so this says so instead of pretending to be a history."""
    now = now or datetime.now(UTC)
    pushes = [e for e in events if e.get("type") == "PushEvent"]
    days = sorted({str(e.get("created_at", ""))[:10] for e in pushes if e.get("created_at")})
    return {
        "events_seen": len(events),
        "push_events": len(pushes),
        "active_days": len(days),
        "first_day": days[0] if days else None,
        "last_day": days[-1] if days else None,
        "note": "GitHub only exposes about the last 90 days of public events.",
        "as_of": now.isoformat(),
    }


def contribution_from_dict(data: dict[str, Any]) -> Contribution:
    return Contribution(**data)


def contribution_to_dict(contribution: Contribution) -> dict[str, Any]:
    return asdict(contribution)
