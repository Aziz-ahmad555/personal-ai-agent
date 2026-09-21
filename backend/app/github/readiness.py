"""Would a recruiter looking at this repository get what they need? Deterministic checks over the
stored snapshot: no LLM and no network. Every check is pass, warn, fail or unknown with the
evidence it used. "Unknown" is a real answer: missing data is never turned into a pass or a
fail. There is no overall score, only what passes and what to fix first."""

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

Status = Literal["pass", "warn", "fail", "unknown"]

MIN_DESCRIPTION_CHARS = 20
MIN_README_WORDS = 150
MIN_INTRO_WORDS = 20
ACTIVE_WITHIN = timedelta(days=365)
MAX_RECORDED = 5

# Folders whose contents are dependencies or build output, not the user's own files.
IGNORED_DIRS = frozenset(
    {
        "node_modules",
        ".venv",
        "venv",
        "env",
        "site-packages",
        "dist",
        "build",
        "vendor",
        "third_party",
    }
)

LIMITATIONS = (
    "Pinned repositories can't be read with this access, so the review covers all your public "
    "repositories rather than the six a visitor sees first.",
    "README checks look at structure (length, sections, images, code), not whether the writing is "
    "any good. That's a judgement this review doesn't make.",
    "Tests, CI and committed-file checks go by file names, not contents. A `tests/` folder proves "
    "there are tests, not that they pass.",
    "Only GitHub Actions, CircleCI, GitLab CI, Travis, Azure Pipelines and Jenkins files count "
    "as CI.",
    "Private repositories aren't included; this connection can only see public ones.",
)

SETUP_HEADINGS = (
    "install",
    "installation",
    "setup",
    "set up",
    "getting started",
    "quick start",
    "quickstart",
    "usage",
    "run",
    "running",
    "how to run",
    "build",
    "development",
    "requirements",
    "prerequisites",
)
VISUAL_HEADINGS = ("demo", "screenshot", "screenshots", "preview", "demo video")
RUN_COMMANDS = re.compile(
    r"^\s*(\$\s*)?(pip3?|python3?|npm|npx|yarn|pnpm|docker|docker-compose|git clone|make|uv|poetry|"
    r"cargo|go run|go build|java|mvn|gradle|flask|uvicorn|streamlit|node|\./)\b",
    re.IGNORECASE | re.MULTILINE,
)
DEMO_LINK = re.compile(
    r"(youtu\.be|youtube\.com|loom\.com|vimeo\.com|\.gif\b|\.mp4\b|\.webm\b)", re.IGNORECASE
)
THROWAWAY_NAME = re.compile(
    r"^(test|testing|untitled|temp|tmp|sample|practice|new[-_ ]?repo|new[-_ ]?project|"
    r"my[-_ ]?project|"
    r"hello[-_ ]?world|first[-_ ]?repo|repo|project)[-_ ]?\d*$",
    re.IGNORECASE,
)

# --- what to record from the file tree ------------------------------------------------------

_TEST_FILE = re.compile(
    r"(^test_.+\.py$|.+_test\.py$|.+\.(test|spec)\.(js|jsx|ts|tsx|mjs)$|.+_test\.go$|.+Tests?\.java$)"
)
_TEST_DIRS = frozenset({"tests", "test", "__tests__", "spec", "e2e"})
_CI_FILES = frozenset(
    {
        ".gitlab-ci.yml",
        "jenkinsfile",
        ".travis.yml",
        "azure-pipelines.yml",
        "bitbucket-pipelines.yml",
    }
)
_SECRET_NAMES = frozenset(
    {
        ".env",
        ".env.local",
        ".env.production",
        ".env.development",
        "id_rsa",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        "credentials.json",
        "secrets.json",
        "secrets.yml",
        "secrets.yaml",
    }
)
_SECRET_SUFFIXES = (".pem", ".p12", ".pfx")
_SAFE_MARKERS = (".example", ".sample", ".template", ".dist")
_JUNK_NAMES = frozenset({".ds_store", "thumbs.db"})
_JUNK_SUFFIXES = (".pyc", ".part", ".swp")
_JUNK_DIRS = frozenset({"__pycache__", "node_modules"})


def is_secret_name(name: str) -> bool:
    """A file name that usually holds credentials. Example, sample and template files don't."""
    lowered = name.lower()
    if any(marker in lowered for marker in _SAFE_MARKERS):
        return False
    return (
        lowered in _SECRET_NAMES
        or lowered.endswith(_SECRET_SUFFIXES)
        or (lowered.startswith("service-account") and lowered.endswith(".json"))
    )


def is_junk_name(name: str) -> bool:
    lowered = name.lower()
    return lowered in _JUNK_NAMES or lowered.endswith(_JUNK_SUFFIXES) or name in _JUNK_DIRS


def notable_paths(entries: list[tuple[str, str]]) -> dict[str, list[str]]:
    """The few paths the readiness checks care about, picked out of the whole file tree
    (`(path, "blob" | "tree")` pairs), so a large repo costs one small JSON value, not its
    listing."""
    found: dict[str, list[str]] = {"tests": [], "ci": [], "secrets": [], "junk": []}

    def add(kind: str, path: str) -> None:
        if len(found[kind]) < MAX_RECORDED and path not in found[kind]:
            found[kind].append(path)

    junk_prefixes: list[str] = []
    for path, kind in sorted(entries):
        parts = path.split("/")
        name = parts[-1]
        lowered = name.lower()
        if kind == "tree":
            if name in _JUNK_DIRS:
                add("junk", path)
                junk_prefixes.append(path + "/")
            continue
        if any(path.startswith(prefix) for prefix in junk_prefixes):
            continue  # inside committed node_modules and the like: one finding is enough
        vendored = any(part in IGNORED_DIRS for part in parts[:-1])
        if not vendored:
            in_test_dir = any(part in _TEST_DIRS for part in parts[:-1])
            if _TEST_FILE.match(name) or (in_test_dir and not lowered.startswith("readme")):
                add("tests", path)
            in_workflows = path.startswith(".github/workflows/") and lowered.endswith(
                (".yml", ".yaml")
            )
            if (
                in_workflows
                or path == ".circleci/config.yml"
                or (len(parts) == 1 and lowered in _CI_FILES)
            ):
                add("ci", path)
        if is_secret_name(name):
            add("secrets", path)
        if is_junk_name(name):
            add("junk", path)
    return found


# --- README structure -----------------------------------------------------------------------

_README_NAMES = ("readme", "readme.md", "readme.markdown", "readme.rst", "readme.txt")


def readme_candidate(root_names: list[str]) -> str | None:
    """The README file in the repository root, if there is one."""
    by_lower = {name.lower(): name for name in root_names}
    for wanted in _README_NAMES:
        if wanted in by_lower:
            return by_lower[wanted]
    return None


def is_markdown(path: str) -> bool:
    return path.lower().endswith((".md", ".markdown")) or "." not in path


def _strip_fences(text: str) -> tuple[str, list[str]]:
    """The text without fenced code blocks, and the contents of each block."""
    prose: list[str] = []
    blocks: list[str] = []
    current: list[str] | None = None
    fence = ""
    for line in text.splitlines():
        stripped = line.strip()
        marker = stripped[:3]
        if current is None and marker in ("```", "~~~"):
            current, fence = [], marker
            continue
        if current is not None and stripped.startswith(fence):
            blocks.append("\n".join(current))
            current = None
            continue
        (prose if current is None else current).append(line)
    if current is not None:  # an unterminated fence still counts as a block
        blocks.append("\n".join(current))
    return "\n".join(prose), blocks


def readme_metrics(text: str, path: str) -> dict[str, Any]:
    """The structure of a README, without keeping its text."""
    markdown = is_markdown(path)
    prose, blocks = _strip_fences(text)
    prose = re.sub(r"<!--.*?-->", "", prose, flags=re.DOTALL)
    words = len(re.findall(r"[A-Za-z0-9_'’-]+", prose))
    headings = [
        re.sub(r"[#\s]+$", "", line.lstrip("#").strip())
        for line in prose.splitlines()
        if re.match(r"^#{1,6}\s+\S", line)
    ]
    images = len(re.findall(r"!\[[^\]]*\]\([^)]+\)", prose)) + len(
        re.findall(r"<img\b", prose, flags=re.IGNORECASE)
    )
    intro_words = 0
    paragraph: list[str] = []
    for line in prose.splitlines() + [""]:
        stripped = line.strip()
        is_noise = (
            stripped.startswith(("#", "![", "<img", "[![", "<p", "<div", "<br", "|", "-", "*", "="))
            or not stripped
        )
        if not is_noise:
            paragraph.append(stripped)
            continue
        if paragraph:
            intro_words = len(re.findall(r"[A-Za-z0-9_'’-]+", " ".join(paragraph)))
            break
    lowered_headings = [h.lower() for h in headings]
    return {
        "path": path,
        "present": True,
        "readable": True,
        "structured": markdown,
        "chars": len(text),
        "words": words,
        "headings": headings[:30],
        "code_blocks": len(blocks),
        "images": images,
        "has_demo_link": bool(DEMO_LINK.search(prose)),
        "intro_words": intro_words,
        "has_setup_section": any(
            any(alias in heading for alias in SETUP_HEADINGS) for heading in lowered_headings
        ),
        "has_visual_section": any(
            any(alias in heading for alias in VISUAL_HEADINGS) for heading in lowered_headings
        ),
        "has_run_command": any(RUN_COMMANDS.search(block) for block in blocks),
    }


# --- the checks -----------------------------------------------------------------------------


@dataclass(frozen=True)
class Check:
    key: str
    label: str
    status: Status
    detail: str
    evidence_url: str | None = None
    fix: str | None = None
    weight: int = 0


@dataclass(frozen=True)
class ReviewFacts:
    name: str
    html_url: str
    default_branch: str | None
    description: str | None
    license_spdx: str | None
    topics: list[str]
    pushed_at: datetime | None
    is_fork: bool
    is_archived: bool
    details_fetched: bool
    root_files: list[str]
    tree_truncated: bool = False
    # None = never collected (an older sync); a dict, even an empty one, means it was collected.
    notable: dict[str, list[str]] | None = None
    readme: dict[str, Any] | None = None


@dataclass(frozen=True)
class RepoReview:
    name: str
    html_url: str
    reviewed: bool
    reason: str | None
    checks: list[Check] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(c.status == "pass" for c in self.checks)

    @property
    def unknown(self) -> int:
        return sum(c.status == "unknown" for c in self.checks)


@dataclass(frozen=True)
class Fix:
    repo: str | None
    repo_url: str | None
    check_key: str
    label: str
    status: Status
    detail: str
    fix: str
    evidence_url: str | None


WEIGHTS = {
    "secrets": 10,
    "readme": 9,
    "license": 8,
    "description": 7,
    "readme_setup": 6,
    "tests": 5,
    "readme_substance": 5,
    "readme_example": 4,
    "readme_visual": 3,
    "topics": 3,
    "ci": 3,
    "junk": 3,
    "gitignore": 2,
    "activity": 2,
    "name": 1,
    "profile_readme": 4,
    "bio": 3,
    "name_set": 2,
    "contact": 2,
    "bar": 6,
}

FIXES = {
    "description": "Add a one-line description under the repository name: what it is and who it "
    "is for.",
    "readme": "Add a README.md. It's the first thing a visitor reads: what it does, how to run it, "
    "and a screenshot.",
    "readme_substance": "Expand the README to a short intro paragraph plus what the project does "
    "and "
    "how it works (150+ words).",
    "readme_setup": "Add an Installation or Usage section with the exact commands to run the "
    "project.",
    "readme_visual": "Add a screenshot, GIF or demo link. Recruiters skim, and a picture is "
    "faster than "
    "text.",
    "readme_example": "Add a fenced code block showing how to install or run it.",
    "license": "Add a LICENSE file. If you're happy for others to reuse the code, MIT is a common "
    "choice; choosealicense.com explains the options.",
    "topics": "Add a few topics (for example the language and domain) so the repository is "
    "searchable.",
    "tests": "Add automated tests, even a few. A tests folder shows you care whether it works.",
    "ci": "Add a CI workflow (for example GitHub Actions) that runs the tests on each push.",
    "gitignore": "Add a .gitignore so build output, caches and environment files stay out of the "
    "repo.",
    "secrets": "Remove the file from the repository and rotate anything it contained; deleting it "
    "later doesn't remove it from history.",
    "junk": "Delete these files and add them to .gitignore.",
    "activity": "Push a recent commit, or archive the repository so it doesn't look abandoned.",
    "name": "Rename the repository to say what it is.",
    "profile_readme": "Create a public repository named exactly like your username with a README; "
    "GitHub shows it at the top of your profile.",
    "bio": "Add a short bio to your GitHub profile: what you do and what you're looking for.",
    "name_set": "Add your real name to your GitHub profile.",
    "contact": "Add a location or a website to your GitHub profile so people know how to reach "
    "you.",
    "bar": "Bring more repositories up to the bar: a description, a README and a license.",
}


def _c(
    key: str,
    label: str,
    status: Status,
    detail: str,
    *,
    url: str | None = None,
) -> Check:
    return Check(
        key=key,
        label=label,
        status=status,
        detail=detail,
        evidence_url=url,
        fix=FIXES.get(key) if status in ("warn", "fail") else None,
        weight=WEIGHTS.get(key, 0),
    )


RESYNC = "Sync again to include this."


def _blob(facts: ReviewFacts, path: str) -> str:
    return f"{facts.html_url}/blob/{facts.default_branch or 'HEAD'}/{path}"


def _repo_checks(facts: ReviewFacts, now: datetime) -> list[Check]:
    checks: list[Check] = []

    description = " ".join((facts.description or "").split())
    if len(description) >= MIN_DESCRIPTION_CHARS:
        checks.append(_c("description", "Has a description", "pass", f"“{description[:80]}”"))
    elif description:
        checks.append(
            _c("description", "Has a description", "fail", f"Only {len(description)} characters.")
        )
    else:
        checks.append(_c("description", "Has a description", "fail", "No description is set."))

    checks.append(_readme_presence(facts))
    checks.extend(_readme_content(facts))

    if facts.license_spdx and facts.license_spdx != "NOASSERTION":
        checks.append(_c("license", "Has a license", "pass", f"Licensed {facts.license_spdx}."))
    elif facts.license_spdx == "NOASSERTION" or any(
        re.fullmatch(r"(license|licence|copying)([.-]\w+)?", name, re.IGNORECASE)
        for name in facts.root_files
    ):
        checks.append(
            _c(
                "license",
                "Has a license",
                "pass",
                "There's a license file, though GitHub couldn't tell which license it is.",
            )
        )
    elif facts.tree_truncated:
        checks.append(
            _c(
                "license",
                "Has a license",
                "unknown",
                "GitHub cut off the file list, so a license file may exist.",
            )
        )
    else:
        checks.append(
            _c(
                "license",
                "Has a license",
                "fail",
                "No license, so nobody is allowed to reuse the code.",
            )
        )

    if facts.topics:
        checks.append(_c("topics", "Has topics", "pass", ", ".join(facts.topics[:6])))
    else:
        checks.append(_c("topics", "Has topics", "warn", "No topics are set."))

    checks.extend(_file_checks(facts))

    if ".gitignore" in facts.root_files:
        checks.append(_c("gitignore", "Has a .gitignore", "pass", "A .gitignore is present."))
    elif facts.tree_truncated:
        checks.append(
            _c("gitignore", "Has a .gitignore", "unknown", "GitHub cut off the file list.")
        )
    else:
        checks.append(
            _c("gitignore", "Has a .gitignore", "warn", "No .gitignore in the repository root.")
        )

    if facts.pushed_at is None:
        checks.append(_c("activity", "Recently active", "unknown", "No push date is recorded."))
    else:
        pushed = facts.pushed_at if facts.pushed_at.tzinfo else facts.pushed_at.replace(tzinfo=UTC)
        age_days = (now - pushed).days
        if now - pushed <= ACTIVE_WITHIN:
            checks.append(
                _c("activity", "Recently active", "pass", f"Last push {pushed:%Y-%m-%d}.")
            )
        else:
            checks.append(
                _c(
                    "activity",
                    "Recently active",
                    "warn",
                    f"Last push {pushed:%Y-%m-%d}, {age_days} days ago.",
                )
            )

    if THROWAWAY_NAME.match(facts.name):
        checks.append(
            _c("name", "Has a meaningful name", "warn", f"“{facts.name}” looks like a placeholder.")
        )
    else:
        checks.append(_c("name", "Has a meaningful name", "pass", f"“{facts.name}”"))
    return checks


def _readme_presence(facts: ReviewFacts) -> Check:
    path = readme_candidate(facts.root_files)
    if path:
        return _c(
            "readme",
            "Has a README",
            "pass",
            f"{path} in the repository root.",
            url=_blob(facts, path),
        )
    if facts.tree_truncated:
        return _c(
            "readme",
            "Has a README",
            "unknown",
            "GitHub cut off the file list, so a README may exist.",
        )
    return _c("readme", "Has a README", "fail", "No README in the repository root.")


def _readme_content(facts: ReviewFacts) -> list[Check]:
    """Checks on what the README contains. Left out entirely when there is no README, since
    'no README' has already been counted once."""
    path = readme_candidate(facts.root_files)
    if path is None:
        return []
    data = facts.readme
    url = _blob(facts, path)
    checks_meta = (
        ("readme_substance", "README explains the project"),
        ("readme_setup", "README says how to run it"),
        ("readme_visual", "README has a screenshot or demo"),
        ("readme_example", "README has a code example"),
    )
    if data is None:
        return [_c(key, label, "unknown", RESYNC, url=url) for key, label in checks_meta]
    if not data.get("readable"):
        reason = data.get("reason") or "It couldn't be read."
        return [
            _c(key, label, "unknown", f"README {reason}", url=url) for key, label in checks_meta
        ]

    checks: list[Check] = []
    words, intro = int(data.get("words", 0)), int(data.get("intro_words", 0))
    problems = []
    if words < MIN_README_WORDS:
        problems.append(f"only {words} words (aim for {MIN_README_WORDS}+)")
    if data.get("structured", True) and intro < MIN_INTRO_WORDS:
        problems.append("no clear intro paragraph")
    if problems:
        checks.append(
            _c(
                "readme_substance",
                checks_meta[0][1],
                "warn",
                "; ".join(problems).capitalize() + ".",
                url=url,
            )
        )
    else:
        checks.append(
            _c(
                "readme_substance",
                checks_meta[0][1],
                "pass",
                f"{words} words with an intro paragraph.",
                url=url,
            )
        )

    if not data.get("structured", True):
        note = "It isn't Markdown, so its sections can't be checked."
        checks.extend(_c(key, label, "unknown", note, url=url) for key, label in checks_meta[1:])
        return checks

    has_setup = data.get("has_setup_section") or data.get("has_run_command")
    checks.append(
        _c(
            "readme_setup",
            checks_meta[1][1],
            "pass",
            "It has an install or usage section or run commands.",
            url=url,
        )
        if has_setup
        else _c(
            "readme_setup",
            checks_meta[1][1],
            "warn",
            "No install or usage section, and no run commands.",
            url=url,
        )
    )
    has_visual = (
        data.get("images", 0) > 0 or data.get("has_demo_link") or data.get("has_visual_section")
    )
    checks.append(
        _c(
            "readme_visual",
            checks_meta[2][1],
            "pass",
            "It has an image, video or demo link.",
            url=url,
        )
        if has_visual
        else _c("readme_visual", checks_meta[2][1], "warn", "No image, GIF or demo link.", url=url)
    )
    blocks = int(data.get("code_blocks", 0))
    checks.append(
        _c("readme_example", checks_meta[3][1], "pass", f"{blocks} code block(s).", url=url)
        if blocks
        else _c("readme_example", checks_meta[3][1], "warn", "No code blocks.", url=url)
    )
    return checks


def _file_checks(facts: ReviewFacts) -> list[Check]:
    """Tests, CI, committed secrets and junk. A hit is always reported; the absence of one is
    only trusted when the file list was collected and complete."""
    notable = facts.notable
    root_hits = {
        "secrets": [n for n in facts.root_files if is_secret_name(n)],
        "junk": [n for n in facts.root_files if is_junk_name(n)],
    }
    known = (notable is not None) and not facts.tree_truncated

    def found(kind: str) -> list[str]:
        merged = list(root_hits.get(kind, []))
        for path in (notable or {}).get(kind, []):
            if path not in merged:
                merged.append(path)
        return merged

    checks: list[Check] = []
    tests, ci = found("tests"), found("ci")
    for key, label, hits, missing_detail in (
        ("tests", "Has automated tests", tests, "No test files or test folders found."),
        ("ci", "Has CI", ci, "No CI configuration found."),
    ):
        if hits:
            checks.append(
                _c(key, label, "pass", f"Found {', '.join(hits[:3])}.", url=_blob(facts, hits[0]))
            )
        elif known:
            checks.append(_c(key, label, "warn", missing_detail))
        else:
            checks.append(
                _c(
                    key,
                    label,
                    "unknown",
                    RESYNC if notable is None else "GitHub cut off the file list.",
                )
            )

    secrets, junk = found("secrets"), found("junk")
    if secrets:
        checks.append(
            _c(
                "secrets",
                "No secret-looking files committed",
                "fail",
                f"Committed: {', '.join(secrets[:3])}. Judged by file name only.",
                url=_blob(facts, secrets[0]),
            )
        )
    elif known:
        checks.append(
            _c("secrets", "No secret-looking files committed", "pass", "None found by file name.")
        )
    else:
        checks.append(
            _c(
                "secrets",
                "No secret-looking files committed",
                "unknown",
                RESYNC if notable is None else "GitHub cut off the file list.",
            )
        )
    if junk:
        checks.append(
            _c(
                "junk",
                "No junk files committed",
                "warn",
                f"Committed: {', '.join(junk[:3])}.",
                url=_blob(facts, junk[0]),
            )
        )
    elif known:
        checks.append(_c("junk", "No junk files committed", "pass", "None found."))
    else:
        checks.append(
            _c(
                "junk",
                "No junk files committed",
                "unknown",
                RESYNC if notable is None else "GitHub cut off the file list.",
            )
        )
    return checks


def review_repo(facts: ReviewFacts, *, now: datetime | None = None) -> RepoReview:
    now = now or datetime.now(UTC)
    if facts.is_fork:
        return RepoReview(
            facts.name, facts.html_url, False, "A fork, so it isn't reviewed as your work."
        )
    if facts.is_archived:
        return RepoReview(facts.name, facts.html_url, False, "Archived, so it isn't reviewed.")
    if not facts.details_fetched:
        return RepoReview(facts.name, facts.html_url, False, "Its details couldn't be read yet.")
    return RepoReview(facts.name, facts.html_url, True, None, _repo_checks(facts, now))


def _bar_met(review: RepoReview) -> bool:
    core = {c.key: c.status for c in review.checks}
    return all(core.get(key) == "pass" for key in ("description", "readme", "license"))


def review_profile(
    profile: dict[str, Any] | None, login: str, reviews: list[RepoReview], repo_names: list[str]
) -> list[Check]:
    """Account-level checks. `profile` is None for a connection synced before these existed."""
    checks: list[Check] = []
    need = RESYNC
    if profile is None:
        checks.extend(
            _c(key, label, "unknown", need)
            for key, label in (
                ("name_set", "Name is set"),
                ("bio", "Bio is set"),
                ("contact", "Has a location or website"),
            )
        )
    else:
        name = (profile.get("name") or "").strip()
        checks.append(
            _c("name_set", "Name is set", "pass", name)
            if name
            else _c("name_set", "Name is set", "warn", "No name is set.")
        )
        bio = " ".join((profile.get("bio") or "").split())
        checks.append(
            _c("bio", "Bio is set", "pass", f"“{bio[:80]}”")
            if bio
            else _c("bio", "Bio is set", "warn", "No bio is set.")
        )
        location, blog = (
            (profile.get("location") or "").strip(),
            (profile.get("blog") or "").strip(),
        )
        checks.append(
            _c(
                "contact",
                "Has a location or website",
                "pass",
                ", ".join(v for v in (location, blog) if v),
            )
            if location or blog
            else _c("contact", "Has a location or website", "warn", "Neither is set.")
        )

    has_profile_readme = any(n.lower() == login.lower() for n in repo_names)
    profile_url = f"https://github.com/{login}/{login}"
    checks.append(
        _c(
            "profile_readme",
            "Has a profile README",
            "pass",
            f"{login}/{login} exists.",
            url=profile_url,
        )
        if has_profile_readme
        else _c(
            "profile_readme", "Has a profile README", "warn", f"No public repository named {login}."
        )
    )

    reviewed = [r for r in reviews if r.reviewed]
    if not reviewed:
        checks.append(
            _c(
                "bar",
                "Repositories with a description, README and license",
                "unknown",
                "No repositories have been reviewed yet.",
            )
        )
    else:
        meeting = sum(_bar_met(r) for r in reviewed)
        detail = f"{meeting} of {len(reviewed)} reviewed repositories have all three."
        good = meeting >= 3 or meeting == len(reviewed)
        checks.append(
            _c(
                "bar",
                "Repositories with a description, README and license",
                "pass" if good else "warn",
                detail,
            )
        )
    return checks


def top_fixes(reviews: list[RepoReview], profile_checks: list[Check], limit: int = 10) -> list[Fix]:
    """What to do first: failures before warnings, then by how much the check matters."""
    candidates: list[Fix] = []
    for review in reviews:
        for check in review.checks:
            if check.status in ("warn", "fail") and check.fix:
                candidates.append(
                    Fix(
                        review.name,
                        review.html_url,
                        check.key,
                        check.label,
                        check.status,
                        check.detail,
                        check.fix,
                        check.evidence_url,
                    )
                )
    for check in profile_checks:
        if check.status in ("warn", "fail") and check.fix:
            candidates.append(
                Fix(
                    None,
                    None,
                    check.key,
                    check.label,
                    check.status,
                    check.detail,
                    check.fix,
                    check.evidence_url,
                )
            )
    candidates.sort(
        key=lambda f: (
            0 if f.status == "fail" else 1,
            -WEIGHTS.get(f.check_key, 0),
            f.repo or "",
            f.check_key,
        )
    )
    return candidates[:limit]


_MARK = {"pass": "x", "warn": " ", "fail": " ", "unknown": "?"}


def export_markdown(
    login: str,
    as_of: datetime | None,
    reviews: list[RepoReview],
    profile_checks: list[Check],
    fixes: list[Fix],
) -> str:
    """A checklist to paste elsewhere: [x] passes, [ ] needs work, [?] unknown."""
    lines = [f"# GitHub recruiter-readiness: @{login}", ""]
    if as_of:
        lines += [
            f"Based on a sync on {as_of:%Y-%m-%d}. Checks go by file names and README "
            "structure, not quality.",
            "",
        ]
    if fixes:
        lines += ["## Fix first", ""]
        for i, fix in enumerate(fixes, 1):
            where = f"**{fix.repo}**: " if fix.repo else "**Profile**: "
            lines.append(f"{i}. {where}{fix.label}. {fix.fix}")
        lines.append("")
    lines += ["## Profile", ""]
    lines += [f"- [{_MARK[c.status]}] {c.label}: {c.detail}" for c in profile_checks]
    for review in reviews:
        lines += ["", f"## {review.name}", ""]
        if not review.reviewed:
            lines.append(f"Not reviewed: {review.reason}")
            continue
        lines.append(
            f"{review.passed} of {len(review.checks)} checks pass"
            + (f", {review.unknown} unknown." if review.unknown else ".")
        )
        lines.append("")
        lines += [f"- [{_MARK[c.status]}] {c.label}: {c.detail}" for c in review.checks]
    lines.append("")
    return "\n".join(lines)
