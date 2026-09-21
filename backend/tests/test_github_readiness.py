"""The recruiter-readiness checks: pure functions over a repo snapshot, no DB and no network.
The shapes mirror real repos: one with no README at all, one with a stray partial download
committed, one notebook-heavy repo."""

from datetime import UTC, datetime, timedelta

from app.github import readiness as r

NOW = datetime(2026, 9, 22, tzinfo=UTC)
GOOD_README = (
    "# Project\n\n"
    "A real-time platform that detects emergencies from camera feeds and explains what it found "
    "to an operator in plain language so they can act quickly and confidently.\n\n"
    "![screenshot](docs/shot.png)\n\n"
    "## Installation\n\n```bash\npip install -r requirements.txt\npython app.py\n```\n\n"
    + "It works by reading frames, detecting people and objects, and scoring risk. "
    * 12
)


def _facts(**overrides: object) -> r.ReviewFacts:
    fields: dict[str, object] = {
        "name": "AegisAI",
        "html_url": "https://github.com/me/AegisAI",
        "default_branch": "main",
        "description": "Real-time multimodal AI platform for emergency detection",
        "license_spdx": "MIT",
        "topics": ["computer-vision"],
        "pushed_at": NOW - timedelta(days=10),
        "is_fork": False,
        "is_archived": False,
        "details_fetched": True,
        "root_files": ["README.md", ".gitignore", "LICENSE", "app.py"],
        "tree_truncated": False,
        "notable": {
            "tests": ["tests/test_app.py"],
            "ci": [".github/workflows/ci.yml"],
            "secrets": [],
            "junk": [],
        },
        "readme": r.readme_metrics(GOOD_README, "README.md"),
    }
    fields.update(overrides)
    return r.ReviewFacts(**fields)  # type: ignore[arg-type]


def _by_key(review: r.RepoReview) -> dict[str, r.Check]:
    return {c.key: c for c in review.checks}


def _status(facts: r.ReviewFacts) -> dict[str, str]:
    return {k: c.status for k, c in _by_key(r.review_repo(facts, now=NOW)).items()}


# --- README structure -----------------------------------------------------------------------


def test_readme_metrics_read_structure_without_keeping_the_text() -> None:
    metrics = r.readme_metrics(GOOD_README, "README.md")

    assert metrics["structured"] is True
    assert metrics["images"] == 1
    assert metrics["code_blocks"] == 1
    assert metrics["has_setup_section"] is True
    assert metrics["has_run_command"] is True
    assert metrics["intro_words"] >= 20
    assert metrics["words"] >= 150
    assert metrics["headings"] == ["Project", "Installation"]
    assert "text" not in metrics
    assert "real-time platform" not in str(metrics)  # the prose itself isn't stored


def test_code_inside_fences_is_not_counted_as_words_or_headings() -> None:
    text = "# T\n\nIntro sentence here.\n\n```\n# not a heading\nword word word word\n```\n"

    metrics = r.readme_metrics(text, "README.md")

    assert metrics["headings"] == ["T"]
    assert metrics["words"] < 12
    assert metrics["code_blocks"] == 1


def test_an_unterminated_fence_and_html_comments_are_handled() -> None:
    metrics = r.readme_metrics(
        "# T\n<!-- hidden words words words -->\nText.\n```\npip install x\n", "README.md"
    )

    assert metrics["code_blocks"] == 1
    assert metrics["has_run_command"] is True
    assert metrics["words"] < 8


def test_an_intro_is_the_first_real_paragraph_not_badges_or_headings() -> None:
    text = (
        "# Title\n\n[![build](x.svg)](y)\n\n![logo](l.png)\n\n"
        "This tool converts scanned invoices into structured data so accountants can search them "
        "and reconcile payments without retyping anything by hand.\n\n## Usage\n"
    )

    assert r.readme_metrics(text, "README.md")["intro_words"] >= 20
    assert (
        r.readme_metrics("# Title\n\n![logo](l.png)\n\n## Usage\n", "README.md")["intro_words"] == 0
    )


def test_visual_evidence_can_be_an_image_a_video_link_or_a_demo_section() -> None:
    assert r.readme_metrics("![a](b.png)", "README.md")["images"] == 1
    assert r.readme_metrics('<img src="a.png">', "README.md")["images"] == 1
    assert r.readme_metrics("Watch https://youtu.be/abc", "README.md")["has_demo_link"] is True
    assert r.readme_metrics("## Screenshots\n", "README.md")["has_visual_section"] is True
    plain = r.readme_metrics("just text", "README.md")
    assert (plain["images"], plain["has_demo_link"], plain["has_visual_section"]) == (
        0,
        False,
        False,
    )


def test_readme_file_names_and_formats() -> None:
    assert r.readme_candidate(["src", "Readme.MD", "LICENSE"]) == "Readme.MD"
    assert r.readme_candidate(["README", "README.md"]) == "README"
    assert r.readme_candidate(["notes.md"]) is None
    assert r.is_markdown("README.md") and r.is_markdown("README")
    assert not r.is_markdown("README.rst") and not r.is_markdown("README.txt")


# --- what gets recorded from a tree ---------------------------------------------------------


def _tree(*paths: str, folders: tuple[str, ...] = ()) -> list[tuple[str, str]]:
    return [(p, "blob") for p in paths] + [(f, "tree") for f in folders]


def test_tests_ci_secrets_and_junk_are_picked_out_of_a_tree() -> None:
    found = r.notable_paths(
        _tree(
            "tests/test_a.py",
            "web/src/App.test.tsx",
            ".github/workflows/ci.yml",
            ".env",
            "config/server.pem",
            ".DS_Store",
            ".yolov8n-pose.pt.abc.part",
            "src/main.py",
        )
    )

    assert found["tests"] == ["tests/test_a.py", "web/src/App.test.tsx"]
    assert found["ci"] == [".github/workflows/ci.yml"]
    assert found["secrets"] == [".env", "config/server.pem"]
    assert found["junk"] == [".DS_Store", ".yolov8n-pose.pt.abc.part"]


def test_example_env_files_are_not_secrets_and_vendored_tests_are_not_yours() -> None:
    found = r.notable_paths(
        _tree(
            ".env.example",
            ".env.sample",
            "node_modules/pkg/test/a.test.js",
            "venv/lib/tests/test_x.py",
        )
    )

    assert found["secrets"] == []
    assert found["tests"] == []


def test_a_committed_node_modules_is_one_finding_not_thousands() -> None:
    entries = _tree(*[f"node_modules/p{i}/index.js" for i in range(500)], folders=("node_modules",))

    found = r.notable_paths(entries)

    assert found["junk"] == ["node_modules"]


def test_other_ci_systems_and_test_conventions_are_recognised() -> None:
    found = r.notable_paths(
        _tree(".gitlab-ci.yml", "Jenkinsfile", "pkg/util_test.go", "spec/models/x_spec.rb")
    )

    assert found["ci"] == [".gitlab-ci.yml", "Jenkinsfile"]
    assert "pkg/util_test.go" in found["tests"]
    assert "spec/models/x_spec.rb" in found["tests"]  # anything under a spec/ folder


def test_recording_is_capped() -> None:
    found = r.notable_paths(_tree(*[f"tests/t{i}.py" for i in range(50)]))

    assert len(found["tests"]) == r.MAX_RECORDED


# --- a healthy repo -------------------------------------------------------------------------


def test_a_healthy_repo_passes_everything() -> None:
    review = r.review_repo(_facts(), now=NOW)

    assert review.reviewed is True
    assert {c.status for c in review.checks} == {"pass"}
    assert review.passed == len(review.checks) == 15
    assert review.unknown == 0
    assert all(c.fix is None for c in review.checks)  # nothing to fix


# --- each check, in each state --------------------------------------------------------------


def test_description() -> None:
    assert _status(_facts(description=None))["description"] == "fail"
    assert _status(_facts(description="   "))["description"] == "fail"
    short = _by_key(r.review_repo(_facts(description="A bot"), now=NOW))["description"]
    assert short.status == "fail" and "5 characters" in short.detail
    assert _status(_facts())["description"] == "pass"


def test_no_readme_fails_and_its_content_checks_are_left_out_rather_than_double_counted() -> None:
    review = r.review_repo(_facts(root_files=[".gitignore", "phase1_vision"], readme=None), now=NOW)

    checks = _by_key(review)
    assert checks["readme"].status == "fail"
    assert not {"readme_substance", "readme_setup", "readme_visual", "readme_example"} & set(checks)


def test_a_truncated_file_list_makes_a_missing_readme_unknown_not_a_failure() -> None:
    status = _status(
        _facts(root_files=["a.py"], tree_truncated=True, readme=None, license_spdx=None)
    )

    assert status["readme"] == "unknown"
    assert status["license"] == "unknown"
    assert status["gitignore"] == "unknown"


def test_a_readme_with_no_collected_metrics_is_unknown_and_asks_for_a_resync() -> None:
    checks = _by_key(r.review_repo(_facts(readme=None), now=NOW))

    assert checks["readme"].status == "pass"  # the file's presence is known from the root listing
    for key in ("readme_substance", "readme_setup", "readme_visual", "readme_example"):
        assert checks[key].status == "unknown"
        assert "Sync again" in checks[key].detail


def test_an_unreadable_readme_is_unknown_with_the_reason() -> None:
    unreadable = {
        "path": "README.md",
        "present": True,
        "readable": False,
        "reason": "is too large to read",
    }

    checks = _by_key(r.review_repo(_facts(readme=unreadable), now=NOW))

    assert checks["readme_setup"].status == "unknown"
    assert "too large" in checks["readme_setup"].detail


def test_a_thin_readme_warns_on_each_missing_part() -> None:
    thin = r.readme_metrics("# Project\n\nA thing.\n", "README.md")

    checks = _by_key(r.review_repo(_facts(readme=thin), now=NOW))

    assert checks["readme_substance"].status == "warn"
    assert "words" in checks["readme_substance"].detail
    assert "intro" in checks["readme_substance"].detail
    assert checks["readme_setup"].status == "warn"
    assert checks["readme_visual"].status == "warn"
    assert checks["readme_example"].status == "warn"
    assert all(
        checks[k].fix
        for k in ("readme_substance", "readme_setup", "readme_visual", "readme_example")
    )


def test_run_commands_count_as_setup_even_without_a_heading() -> None:
    text = "# P\n\n" + "word " * 200 + "\n\n```\nnpm install\nnpm run dev\n```\n"

    checks = _by_key(r.review_repo(_facts(readme=r.readme_metrics(text, "README.md")), now=NOW))

    assert checks["readme_setup"].status == "pass"
    assert checks["readme_example"].status == "pass"


def test_a_non_markdown_readme_only_gets_its_length_judged() -> None:
    rst = r.readme_metrics("Title\n=====\n\n" + "word " * 200, "README.rst")

    checks = _by_key(
        r.review_repo(
            _facts(root_files=["README.rst", ".gitignore", "LICENSE"], readme=rst), now=NOW
        )
    )

    assert checks["readme_substance"].status == "pass"
    for key in ("readme_setup", "readme_visual", "readme_example"):
        assert checks[key].status == "unknown"
        assert "isn't Markdown" in checks[key].detail


def test_license_states() -> None:
    assert _status(_facts())["license"] == "pass"
    no_license = _by_key(
        r.review_repo(_facts(license_spdx=None, root_files=["README.md", ".gitignore"]), now=NOW)
    )
    assert no_license["license"].status == "fail"
    assert "nobody is allowed to reuse" in no_license["license"].detail
    # A license file GitHub couldn't classify is still a license file.
    assert _status(_facts(license_spdx="NOASSERTION"))["license"] == "pass"
    assert (
        _status(_facts(license_spdx=None, root_files=["README.md", "COPYING", ".gitignore"]))[
            "license"
        ]
        == "pass"
    )
    assert (
        _status(_facts(license_spdx=None, root_files=["README.md", "LICENSE.md", ".gitignore"]))[
            "license"
        ]
        == "pass"
    )


def test_topics_and_names() -> None:
    assert _status(_facts(topics=[]))["topics"] == "warn"
    for placeholder in (
        "test",
        "Untitled",
        "hello-world",
        "new-repo",
        "temp2",
        "My_Project",
        "repo1",
    ):
        assert _status(_facts(name=placeholder))["name"] == "warn", placeholder
    for real in ("AegisAI", "testing-framework-comparison", "smart-campus-ai"):
        assert _status(_facts(name=real))["name"] == "pass", real


def test_activity_uses_a_twelve_month_window() -> None:
    assert _status(_facts(pushed_at=NOW - timedelta(days=364)))["activity"] == "pass"
    old = _by_key(r.review_repo(_facts(pushed_at=NOW - timedelta(days=500)), now=NOW))["activity"]
    assert old.status == "warn" and "500 days ago" in old.detail
    assert _status(_facts(pushed_at=None))["activity"] == "unknown"
    naive = datetime(2026, 9, 1)  # a naive stored datetime is treated as UTC, not crashed on
    assert _status(_facts(pushed_at=naive))["activity"] == "pass"


def test_gitignore() -> None:
    assert _status(_facts(root_files=["README.md", "LICENSE"]))["gitignore"] == "warn"


def test_tests_and_ci_warn_only_when_the_file_list_was_collected() -> None:
    empty = {"tests": [], "ci": [], "secrets": [], "junk": []}

    status = _status(_facts(notable=empty))
    assert (status["tests"], status["ci"]) == ("warn", "warn")

    never_collected = _by_key(r.review_repo(_facts(notable=None), now=NOW))
    assert never_collected["tests"].status == "unknown"
    assert "Sync again" in never_collected["tests"].detail
    truncated = _by_key(r.review_repo(_facts(notable=empty, tree_truncated=True), now=NOW))
    assert truncated["tests"].status == "unknown"
    assert "cut off" in truncated["tests"].detail


def test_a_test_file_seen_at_the_root_counts_even_if_the_tree_was_never_collected() -> None:
    # Root names come from every sync, so a hit is reportable; only the absence needs full data.
    status = _status(
        _facts(notable=None, root_files=["README.md", ".gitignore", "LICENSE", ".env"])
    )

    assert status["secrets"] == "fail"


def test_committed_secrets_fail_and_only_by_file_name() -> None:
    notable = {"tests": [], "ci": [], "secrets": ["backend/.env", "keys/id_rsa"], "junk": []}

    check = _by_key(r.review_repo(_facts(notable=notable), now=NOW))["secrets"]

    assert check.status == "fail"
    assert "backend/.env" in check.detail
    assert "file name only" in check.detail
    assert check.evidence_url == "https://github.com/me/AegisAI/blob/main/backend/.env"
    assert "rotate" in (check.fix or "")


def test_junk_files_warn_and_an_example_env_does_not() -> None:
    notable = {"tests": [], "ci": [], "secrets": [], "junk": [".yolov8n-pose.pt.38fb.part"]}

    checks = _by_key(
        r.review_repo(
            _facts(
                notable=notable, root_files=["README.md", ".gitignore", "LICENSE", ".env.example"]
            ),
            now=NOW,
        )
    )

    assert checks["junk"].status == "warn"
    assert ".part" in checks["junk"].detail
    assert checks["secrets"].status == "pass"


# --- not reviewed ---------------------------------------------------------------------------


def test_forks_archives_and_unread_repos_are_not_reviewed_and_say_why() -> None:
    fork = r.review_repo(_facts(is_fork=True), now=NOW)
    archived = r.review_repo(_facts(is_archived=True), now=NOW)
    unread = r.review_repo(_facts(details_fetched=False), now=NOW)

    assert [x.reviewed for x in (fork, archived, unread)] == [False, False, False]
    assert "fork" in (fork.reason or "")
    assert "Archived" in (archived.reason or "")
    assert "couldn't be read" in (unread.reason or "")
    assert fork.checks == []


# --- account-level --------------------------------------------------------------------------

PROFILE = {
    "name": "Aziz Ahmad",
    "bio": "ML engineer building vision systems",
    "location": "Lahore",
    "blog": "",
}


def _profile(
    profile: dict | None, reviews: list[r.RepoReview], names: list[str] | None = None
) -> dict[str, r.Check]:
    checks = r.review_profile(
        profile, "me", reviews, names if names is not None else [x.name for x in reviews]
    )
    return {c.key: c for c in checks}


def test_profile_checks_pass_when_everything_is_set() -> None:
    good = r.review_repo(_facts(), now=NOW)

    checks = _profile(PROFILE, [good, good, good], ["a", "b", "me"])

    assert {c.status for c in checks.values()} == {"pass"}
    assert checks["profile_readme"].evidence_url == "https://github.com/me/me"


def test_profile_gaps_warn_with_a_fix() -> None:
    checks = _profile({"name": None, "bio": "", "location": None, "blog": ""}, [], ["a"])

    for key in ("name_set", "bio", "contact", "profile_readme"):
        assert checks[key].status == "warn"
        assert checks[key].fix
    assert checks["bar"].status == "unknown"  # nothing reviewed yet


def test_a_profile_from_an_older_sync_is_unknown_not_empty() -> None:
    checks = _profile(None, [], [])

    assert checks["bio"].status == "unknown"
    assert "Sync again" in checks["bio"].detail


def test_the_bar_needs_three_good_repos_or_all_of_a_small_set() -> None:
    good = r.review_repo(_facts(), now=NOW)
    bad = r.review_repo(
        _facts(license_spdx=None, root_files=[".gitignore"], description=None), now=NOW
    )

    assert _profile(PROFILE, [good], ["a"])["bar"].status == "pass"  # all of one
    assert _profile(PROFILE, [good, bad], ["a", "b"])["bar"].status == "warn"
    assert _profile(PROFILE, [good, good, good, bad], list("abcd"))["bar"].status == "pass"
    detail = _profile(PROFILE, [good, bad], ["a", "b"])["bar"].detail
    assert detail == "1 of 2 reviewed repositories have all three."


def test_unreviewed_repos_do_not_count_toward_the_bar() -> None:
    good = r.review_repo(_facts(), now=NOW)
    fork = r.review_repo(_facts(is_fork=True), now=NOW)

    assert (
        _profile(PROFILE, [good, fork], ["a", "b"])["bar"].detail
        == "1 of 1 reviewed repositories have all three."
    )


# --- fixing first ---------------------------------------------------------------------------


def test_fixes_put_failures_first_then_what_matters_most() -> None:
    weak = r.review_repo(
        _facts(
            name="plant",
            license_spdx=None,
            root_files=[".gitignore", "README.md"],
            topics=[],
            notable={"tests": [], "ci": [], "secrets": ["a/.env"], "junk": []},
            readme=r.readme_metrics("# P\n\nA thing.\n", "README.md"),
        ),
        now=NOW,
    )

    fixes = r.top_fixes([weak], [], limit=50)

    keys = [f.check_key for f in fixes]
    assert keys[0] == "secrets"  # a leaked file outranks everything
    assert keys.index("license") < keys.index("readme_setup")
    fail_positions = [i for i, f in enumerate(fixes) if f.status == "fail"]
    warn_positions = [i for i, f in enumerate(fixes) if f.status == "warn"]
    assert max(fail_positions) < min(warn_positions)  # every failure before every warning
    assert all(f.fix for f in fixes)


def test_fixes_never_include_unknowns_or_passes_and_are_limited() -> None:
    review = r.review_repo(_facts(notable=None, readme=None), now=NOW)

    assert r.top_fixes([review], []) == []  # only unknowns, nothing provable to fix
    weak = r.review_repo(
        _facts(topics=[], description=None, license_spdx=None, root_files=[]), now=NOW
    )
    assert len(r.top_fixes([weak], [], limit=2)) == 2


def test_profile_fixes_are_included_and_name_no_repo() -> None:
    checks = r.review_profile({"name": "x", "bio": "", "location": "", "blog": ""}, "me", [], [])

    fixes = r.top_fixes([], checks)

    assert {f.check_key for f in fixes} == {"bio", "contact", "profile_readme"}
    assert all(f.repo is None for f in fixes)


# --- the Markdown export --------------------------------------------------------------------


def test_the_markdown_export_is_a_checklist_with_states_and_reasons() -> None:
    good = r.review_repo(_facts(), now=NOW)
    weak = r.review_repo(
        _facts(name="plant", license_spdx=None, root_files=[".gitignore"], notable=None), now=NOW
    )
    fork = r.review_repo(_facts(name="upstream", is_fork=True), now=NOW)
    profile = r.review_profile(PROFILE, "me", [good, weak, fork], ["AegisAI", "plant", "upstream"])
    fixes = r.top_fixes([good, weak, fork], profile)

    text = r.export_markdown("me", NOW, [good, weak, fork], profile, fixes)

    assert text.startswith("# GitHub recruiter-readiness: @me")
    assert "Based on a sync on 2026-09-22" in text
    assert "## Fix first" in text
    assert "1. **plant**: " in text
    assert "- [x] Has a description:" in text
    assert "- [ ] Has a license:" in text
    assert "- [?] Has automated tests:" in text  # unknown is neither ticked nor failed
    assert "15 of 15 checks pass." in text
    assert "## upstream\n\nNot reviewed: A fork" in text
    assert text.endswith("\n")


def test_the_export_without_a_sync_date_or_fixes_is_still_valid() -> None:
    good = r.review_repo(_facts(), now=NOW)

    text = r.export_markdown("me", None, [good], [], [])

    assert "Based on a sync" not in text
    assert "## Fix first" not in text


def test_the_limitations_are_stated_plainly() -> None:
    joined = " ".join(r.LIMITATIONS)

    assert "Pinned repositories" in joined
    assert "not whether the writing is any good" in joined
    assert "file names" in joined
    assert "Private repositories" in joined


def test_multi_line_descriptions_and_bios_are_shown_on_one_line() -> None:
    facts = _facts(description="Real-time platform\nfor emergency detection  and response")
    description = _by_key(r.review_repo(facts, now=NOW))["description"]
    bio_profile = {
        "name": "A",
        "bio": "AI / ML Interest\nAspiring Engineer",
        "location": "x",
        "blog": "",
    }
    bio = {c.key: c for c in r.review_profile(bio_profile, "me", [], [])}["bio"]

    assert "\n" not in description.detail
    assert "platform for emergency detection and response" in description.detail
    assert bio.detail == "“AI / ML Interest Aspiring Engineer”"
