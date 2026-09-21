"""Manifest parsing, the skill tables, and how repo facts become (or don't become) proposals.
Pure functions: no DB, no network. The repo shapes mirror real ones: a Python project, a mixed
JS/Python project, and a notebook-dominated repo whose commits aren't attributed to the owner."""

from datetime import UTC, datetime

from app.github import catalog
from app.github.derive import (
    DependencyFact,
    ExistingSkill,
    RepoFacts,
    contribution_from_dict,
    contribution_to_dict,
    derive,
    evidence_text,
    fingerprint,
    summarize_events,
)


def _repo(name: str = "AegisAI", **overrides: object) -> RepoFacts:
    fields: dict[str, object] = {
        "name": name,
        "full_name": f"me/{name}",
        "html_url": f"https://github.com/me/{name}",
        "is_fork": False,
        "is_archived": False,
        "languages": {"Python": 114_846, "HTML": 62_339},
        "authored_commits": 43,
        "last_commit_at": "2026-09-12T10:00:00Z",
        "root_files": [],
        "dependencies": [],
        **overrides,
    }
    return RepoFacts(**fields)  # type: ignore[arg-type]


def _by_name(result) -> dict:  # type: ignore[no-untyped-def]
    return {p.skill_name: p for p in result.proposals}


# --- manifest parsing -----------------------------------------------------------------------


def test_requirements_txt_names_are_extracted_and_junk_is_skipped() -> None:
    text = """
# a comment
fastapi[standard]>=0.110  # trailing comment
Flask==3.0.0
torch ; python_version >= "3.9"
-r other.txt
-e .
git+https://github.com/x/y.git
--hash=abc
scikit_learn~=1.4
pkg @ https://example.com/pkg.whl

"""
    assert catalog.parse_requirements(text) == ["fastapi", "flask", "torch", "scikit-learn", "pkg"]


def test_pyproject_reads_pep621_optional_groups_poetry_and_ignores_python_itself() -> None:
    text = """
[project]
dependencies = ["FastAPI>=0.1", "sqlalchemy[asyncio]"]
[project.optional-dependencies]
dev = ["pytest>=8"]
[dependency-groups]
lint = ["ruff"]
[tool.poetry.dependencies]
python = "^3.11"
Django = "^5"
"""
    names = catalog.parse_pyproject(text)

    assert {"fastapi", "sqlalchemy", "pytest", "ruff", "django"} <= set(names)
    assert "python" not in names


def test_broken_manifests_yield_nothing_instead_of_raising() -> None:
    assert catalog.parse_pyproject("not [valid toml") == []
    assert catalog.parse_package_json("{nope") == []
    assert catalog.parse_package_json("[1, 2]") == []
    assert catalog.parse_requirements("") == []


def test_package_json_reads_all_dependency_sections() -> None:
    text = (
        '{"dependencies": {"react": "^19"}, "devDependencies": {"Vitest": "1"}, '
        '"peerDependencies": {"three": "*"}}'
    )

    assert catalog.parse_package_json(text) == ["react", "vitest", "three"]


def test_dependencies_become_distinct_skills_in_first_seen_order() -> None:
    text = (
        '{"dependencies": {"react": "1", "react-dom": "1", "left-pad": "1", '
        '"@tanstack/react-query": "5"}}'
    )

    assert catalog.dependency_skills("package.json", text) == ["React", "TanStack Query"]
    assert catalog.dependency_skills("requirements-dev.txt", "pytest\nnumpy\npytest") == [
        "pytest",
        "NumPy",
    ]
    assert catalog.dependency_skills("README.md", "fastapi") == []


def test_manifest_detection_by_filename() -> None:
    for name in (
        "requirements.txt",
        "requirements-dev.txt",
        "package.json",
        "pyproject.toml",
        "Requirements.TXT",
    ):
        assert catalog.is_manifest(name)
    for name in ("package-lock.json", "setup.py", "notes.txt", "requirements.md"):
        assert not catalog.is_manifest(name)


# --- language evidence ----------------------------------------------------------------------


def test_a_language_needs_enough_bytes_and_smaller_ones_are_explained() -> None:
    result = derive([_repo(languages={"Python": 1_384, "JavaScript": 20_000})], {})

    assert list(_by_name(result)) == ["JavaScript"]
    reasons = {s.subject: s.reason for s in result.skipped}
    assert "Only 1.4 KB" in reasons["AegisAI: Python"]
    assert "under the 5.0 KB" in reasons["AegisAI: Python"]


def test_notebook_bytes_are_never_counted_as_python() -> None:
    plant = _repo(
        "plant-disease-classifier",
        languages={"Jupyter Notebook": 536_469, "Python": 1_384},
        authored_commits=0,
    )

    result = derive([plant], {})

    proposals = _by_name(result)
    assert list(proposals) == ["Jupyter Notebooks"]  # Python is under threshold and stays out
    assert proposals["Jupyter Notebooks"].contributions[0].bytes == 536_469
    reasons = {s.subject: s.reason for s in result.skipped}
    assert "isn't counted as Python" in reasons["plant-disease-classifier: Jupyter Notebook"]


def test_file_types_that_are_not_skills_are_not_proposed() -> None:
    result = derive([_repo(languages={"Python": 20_000, "Dockerfile": 900, "Makefile": 300})], {})

    assert list(_by_name(result)) == ["Python"]
    assert {s.subject for s in result.skipped} == {"AegisAI: Dockerfile", "AegisAI: Makefile"}


# --- exclusions -----------------------------------------------------------------------------


def test_forks_and_archived_repos_are_excluded_and_say_why() -> None:
    result = derive(
        [
            _repo("upstream", is_fork=True),
            _repo("old", is_archived=True),
            _repo("mine", languages={"Go": 9_000}),
        ],
        {},
    )

    assert list(_by_name(result)) == ["Go"]
    reasons = {s.subject: s.reason for s in result.skipped}
    assert "fork" in reasons["upstream"]
    assert "Archived" in reasons["old"]


def test_a_repo_whose_details_could_not_be_fetched_proposes_nothing() -> None:
    result = derive([_repo(details_fetched=False, languages={})], {})

    assert result.proposals == []
    assert "couldn't be fetched" in result.skipped[0].reason


# --- frameworks and tools -------------------------------------------------------------------


def test_dependencies_and_root_files_become_framework_and_tool_evidence() -> None:
    repo = _repo(
        dependencies=[
            DependencyFact(
                "FastAPI",
                "requirements.txt",
                "https://github.com/me/AegisAI/blob/HEAD/requirements.txt",
            )
        ],
        root_files=["README.md", "Dockerfile"],
    )

    proposals = _by_name(derive([repo], {}))

    fastapi = proposals["FastAPI"]
    assert fastapi.kind == "framework"
    assert fastapi.contributions[0].via == "dependency"
    assert fastapi.contributions[0].source_url.endswith("/requirements.txt")
    docker = proposals["Docker"]
    assert docker.kind == "tool"
    assert (
        docker.contributions[0].source_url == "https://github.com/me/AegisAI/blob/HEAD/Dockerfile"
    )


def test_one_skill_across_several_repos_is_one_proposal_with_each_repo_as_evidence() -> None:
    result = derive(
        [
            _repo("a", languages={"Python": 10_000}),
            _repo("b", languages={"Python": 6_000}, authored_commits=5),
        ],
        {},
    )

    python = _by_name(result)["Python"]
    assert [c.repo for c in python.contributions] == ["a", "b"]
    assert len(result.proposals) == 1


# --- attribution ----------------------------------------------------------------------------


def test_zero_attributed_commits_is_labelled_ownership_only_and_still_proposed() -> None:
    result = derive([_repo(authored_commits=0, languages={"Python": 30_000})], {})

    python = _by_name(result)["Python"]
    assert python.attribution == "ownership_only"
    assert python.contributions[0].attribution == "ownership_only"


def test_unknown_commit_counts_are_not_claimed_as_zero() -> None:
    python = _by_name(derive([_repo(authored_commits=None, languages={"Python": 30_000})], {}))[
        "Python"
    ]

    assert python.attribution == "unknown"
    assert "commit attribution unavailable" in evidence_text("me", "Python", python.contributions)


def test_any_attributed_repo_makes_the_proposal_attributed() -> None:
    result = derive(
        [
            _repo("mine", languages={"Python": 9_000}, authored_commits=4),
            _repo("theirs", languages={"Python": 9_000}, authored_commits=0),
        ],
        {},
    )

    assert _by_name(result)["Python"].attribution == "attributed"


def test_attributed_proposals_come_first_then_by_commits() -> None:
    result = derive(
        [
            _repo("owned", languages={"Go": 9_000}, authored_commits=0),
            _repo("busy", languages={"Rust": 9_000}, authored_commits=50),
            _repo("light", languages={"Swift": 9_000}, authored_commits=2),
        ],
        {},
    )

    assert [p.skill_name for p in result.proposals] == ["Rust", "Swift", "Go"]


# --- existing profile skills ----------------------------------------------------------------


def test_an_existing_skill_is_matched_through_the_alias_table_and_keeps_its_name_and_level() -> (
    None
):
    existing = {
        "python": ExistingSkill("python", "advanced"),
        "pytorch": ExistingSkill("PyTorch", None),
    }
    repo = _repo(
        languages={"Python": 40_000},
        dependencies=[DependencyFact("PyTorch", "requirements.txt", "https://x/requirements.txt")],
    )

    proposals = _by_name(derive([repo], existing))

    assert proposals["python"].existing_skill_name == "python"
    assert proposals["python"].existing_level == "advanced"
    assert proposals["PyTorch"].existing_skill_name == "PyTorch"
    assert proposals["PyTorch"].existing_level is None  # exists, but no level to carry forward


def test_a_new_skill_has_no_existing_level() -> None:
    proposal = _by_name(derive([_repo()], {}))["Python"]

    assert (proposal.existing_skill_name, proposal.existing_level) == (None, None)


# --- fingerprints ---------------------------------------------------------------------------


def test_the_fingerprint_ignores_growth_but_changes_with_new_evidence() -> None:
    small = derive([_repo(languages={"Python": 10_000}, authored_commits=5)], {}).proposals[0]
    grown = derive([_repo(languages={"Python": 90_000}, authored_commits=80)], {}).proposals[0]
    another = derive(
        [_repo(languages={"Python": 10_000}), _repo("second", languages={"Python": 10_000})], {}
    ).proposals[0]
    lost_attribution = derive(
        [_repo(languages={"Python": 10_000}, authored_commits=0)], {}
    ).proposals[0]

    assert small.fingerprint == grown.fingerprint
    assert small.fingerprint != another.fingerprint
    assert small.fingerprint != lost_attribution.fingerprint


def test_a_fingerprint_does_not_depend_on_evidence_order() -> None:
    a = derive([_repo("a"), _repo("b")], {}).proposals[0].contributions
    assert fingerprint(a) == fingerprint(list(reversed(a)))


def test_contributions_survive_a_dict_round_trip() -> None:
    contribution = derive([_repo()], {}).proposals[0].contributions[0]

    assert contribution_from_dict(contribution_to_dict(contribution)) == contribution


# --- the sentence that would be saved -------------------------------------------------------


def test_the_evidence_text_states_only_recorded_facts() -> None:
    result = derive(
        [
            _repo("AegisAI", languages={"Python": 114_846}, authored_commits=43),
            _repo("plant", languages={"Python": 30_000}, authored_commits=0),
        ],
        {},
    )

    text = evidence_text("Aziz-ahmad555", "Python", result.proposals[0].contributions)

    assert text == (
        "GitHub (@Aziz-ahmad555): Python — "
        "AegisAI (114.8 KB of Python; 43 commits by this account, last 2026-09-12); "
        "plant (30.0 KB of Python; owned by this account; no commits attributed to it)."
    )


def test_the_evidence_text_for_dependencies_and_files_and_single_commits() -> None:
    repo = _repo(
        authored_commits=1,
        languages={},
        dependencies=[DependencyFact("FastAPI", "pyproject.toml", "https://x/pyproject.toml")],
        root_files=["Dockerfile"],
    )
    proposals = _by_name(derive([repo], {}))

    assert "declared in pyproject.toml" in evidence_text(
        "me", "FastAPI", proposals["FastAPI"].contributions
    )
    text = evidence_text("me", "Docker", proposals["Docker"].contributions)
    assert "has a Dockerfile" in text
    assert "1 commit by this account" in text


# --- activity -------------------------------------------------------------------------------


def test_activity_counts_pushes_and_distinct_days_and_states_its_window() -> None:
    events = [
        {"type": "PushEvent", "created_at": "2026-09-10T08:00:00Z"},
        {"type": "PushEvent", "created_at": "2026-09-10T20:00:00Z"},
        {"type": "PushEvent", "created_at": "2026-09-12T08:00:00Z"},
        {"type": "CreateEvent", "created_at": "2026-09-01T08:00:00Z"},
    ]

    summary = summarize_events(events, now=datetime(2026, 9, 20, tzinfo=UTC))

    assert summary["events_seen"] == 4
    assert summary["push_events"] == 3
    assert summary["active_days"] == 2
    assert (summary["first_day"], summary["last_day"]) == ("2026-09-10", "2026-09-12")
    assert "90 days" in summary["note"]


def test_activity_with_no_events_is_empty_not_invented() -> None:
    summary = summarize_events([])

    assert (summary["push_events"], summary["active_days"], summary["last_day"]) == (0, 0, None)
