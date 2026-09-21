"""The readiness review through the API, on the standard fake account (which, like the real one,
has a repo with no README and a repo with a partial download committed)."""

import pytest
from github_fake import FakeGitHub
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from test_github_proposals import _connect, _sync  # noqa: PLC2701 — shared test helpers

from app.audit.models import AuditLog
from app.github import sync
from app.github.models import GithubRepo


@pytest.fixture
async def reviewed(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> dict:
    await _connect(session_factory)
    await _sync(client, auth_headers, monkeypatch)
    response = await client.get("/github/readiness", headers=auth_headers)
    assert response.status_code == 200
    return response.json()


def _repo(review: dict, name: str) -> dict:
    return next(r for r in review["repos"] if r["name"] == name)


def _checks(review: dict, name: str) -> dict[str, dict]:
    return {c["key"]: c for c in _repo(review, name)["checks"]}


# --- access ---------------------------------------------------------------------------------


async def test_the_review_requires_auth_and_a_connection(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    for path in ("/github/readiness", "/github/readiness/export"):
        assert (await client.get(path)).status_code == 401
        assert (await client.get(path, headers=auth_headers)).status_code == 404


async def test_before_any_sync_there_is_nothing_to_review_and_no_resync_nag(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _connect(session_factory)

    review = (await client.get("/github/readiness", headers=auth_headers)).json()

    assert review["synced"] is False
    assert review["as_of"] is None
    assert review["repos"] == []
    assert review["needs_resync"] is False  # nothing has been synced, so nothing is stale
    assert review["fixes"] == []
    assert review["profile"] == []  # not judged before it has been read
    assert review["limitations"]


# --- the review of the standard account -----------------------------------------------------


async def test_forks_and_archives_are_listed_but_not_reviewed_and_say_why(reviewed: dict) -> None:
    fork = _repo(reviewed, "someone-elses-project")
    archived = _repo(reviewed, "old-experiment")

    assert fork["reviewed"] is False
    assert "fork" in fork["reason"]
    assert archived["reviewed"] is False
    assert "Archived" in archived["reason"]
    assert fork["checks"] == []
    assert (fork["passed"], fork["total"]) == (0, 0)


async def test_a_repo_with_no_readme_fails_once_and_its_readme_content_checks_are_omitted(
    reviewed: dict,
) -> None:
    checks = _checks(reviewed, "AegisAI")

    assert checks["readme"]["status"] == "fail"
    assert "readme_setup" not in checks
    assert checks["description"]["status"] == "pass"
    assert checks["license"]["status"] == "fail"
    assert checks["topics"]["status"] == "warn"
    assert checks["tests"]["status"] == "warn"
    assert checks["ci"]["status"] == "warn"
    assert checks["secrets"]["status"] == "pass"


async def test_a_committed_partial_download_is_flagged_as_junk_with_a_link(reviewed: dict) -> None:
    junk = _checks(reviewed, "smart-campus-ai")["junk"]

    assert junk["status"] == "warn"
    assert ".yolov8n-pose.pt.38fb.part" in junk["detail"]
    assert junk["evidence_url"].endswith("/blob/main/.yolov8n-pose.pt.38fb.part")
    assert "Delete these files" in junk["fix"]


async def test_readme_content_is_judged_from_structure(reviewed: dict) -> None:
    checks = _checks(reviewed, "smart-campus-ai")  # the fake's README is one short line

    assert checks["readme"]["status"] == "pass"
    assert checks["readme"]["evidence_url"].endswith("/blob/main/README.md")
    assert checks["readme_substance"]["status"] == "warn"
    assert checks["readme_setup"]["status"] == "warn"
    assert checks["readme_visual"]["status"] == "warn"


async def test_counts_add_up(reviewed: dict) -> None:
    for repo in reviewed["repos"]:
        statuses = [c["status"] for c in repo["checks"]]
        assert repo["total"] == len(statuses)
        assert repo["passed"] == statuses.count("pass")
        assert repo["unknown"] == statuses.count("unknown")


async def test_the_profile_checks_use_the_synced_profile(reviewed: dict) -> None:
    profile = {c["key"]: c for c in reviewed["profile"]}

    assert profile["name_set"]["status"] == "pass"
    assert profile["bio"]["status"] == "pass"
    assert profile["contact"]["status"] == "pass"
    assert profile["contact"]["detail"] == "Lahore"
    assert profile["profile_readme"]["status"] == "warn"  # no repository named "me"
    assert profile["bar"]["status"] == "warn"
    assert profile["bar"]["detail"] == "0 of 3 reviewed repositories have all three."


async def test_the_fix_list_starts_with_failures_and_never_includes_forks(reviewed: dict) -> None:
    fixes = reviewed["fixes"]

    assert fixes and len(fixes) <= 10
    statuses = [f["status"] for f in fixes]
    assert statuses == sorted(statuses, key=lambda s: 0 if s == "fail" else 1)
    assert fixes[0]["status"] == "fail"
    assert not [f for f in fixes if f["repo"] in ("someone-elses-project", "old-experiment")]
    assert all(f["fix"] for f in fixes)
    assert any(f["repo"] is None for f in fixes) or len(fixes) == 10  # profile fixes rank too


async def test_the_review_says_when_it_is_based_and_what_it_cannot_see(reviewed: dict) -> None:
    assert reviewed["synced"] is True
    assert reviewed["as_of"] is not None
    assert reviewed["needs_resync"] is False
    joined = " ".join(reviewed["limitations"])
    assert "Pinned repositories" in joined
    assert "not whether the writing is any good" in joined


# --- data from an older sync ----------------------------------------------------------------


async def test_data_from_an_older_sync_is_unknown_and_asks_for_a_resync_never_a_failure(
    client: AsyncClient,
    auth_headers: dict[str, str],
    reviewed: dict,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as db:
        await db.execute(
            update(GithubRepo)
            .where(GithubRepo.name == "smart-campus-ai")
            .values(notable_paths=None, readme=None)
        )
        await db.commit()

    review = (await client.get("/github/readiness", headers=auth_headers)).json()

    checks = _checks(review, "smart-campus-ai")
    for key in ("tests", "ci", "secrets", "readme_substance", "readme_setup"):
        assert checks[key]["status"] == "unknown", key
        assert "Sync again" in checks[key]["detail"]
    # A junk file sitting in the repo root is visible even from an older sync, so it still shows.
    assert checks["junk"]["status"] == "warn"
    assert checks["readme"]["status"] == "pass"  # known from the root listing
    assert review["needs_resync"] is True
    fixed = {(f["repo"], f["check_key"]) for f in review["fixes"]}
    assert ("smart-campus-ai", "tests") not in fixed  # an unknown is not a fix


# --- nothing leaves the machine -------------------------------------------------------------


async def test_the_review_makes_no_github_requests(
    client: AsyncClient,
    auth_headers: dict[str, str],
    reviewed: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    silent = FakeGitHub()
    monkeypatch.setattr(sync.httpx, "AsyncClient", silent.client_factory())

    await client.get("/github/readiness", headers=auth_headers)
    await client.get("/github/readiness/export", headers=auth_headers)

    assert silent.requests == []


# --- the export -----------------------------------------------------------------------------


async def test_the_export_is_a_markdown_checklist_and_is_audited(
    client: AsyncClient,
    auth_headers: dict[str, str],
    reviewed: dict,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    response = await client.get("/github/readiness/export", headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["filename"] == "github-readiness-me.md"
    text = body["text"]
    assert text.startswith("# GitHub recruiter-readiness: @me")
    assert "## Fix first" in text
    assert "## AegisAI" in text
    assert "- [ ] Has a README:" in text
    assert "- [x] Has a description:" in text
    assert "## someone-elses-project\n\nNot reviewed: A fork" in text
    async with session_factory() as db:
        entry = (
            await db.execute(select(AuditLog).where(AuditLog.action == "github.readiness.exported"))
        ).scalar_one()
    assert entry.risk_level == "green"
    assert entry.evidence["repos_reviewed"] == 3
