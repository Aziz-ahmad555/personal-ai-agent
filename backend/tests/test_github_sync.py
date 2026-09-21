"""The read-only GitHub reads and the sync that turns them into a snapshot and proposals. All
GitHub HTTP is faked (see github_fake.py): no test reaches the real API."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from github_fake import FakeGitHub, b64, commit, link, ok, repo
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.models import AuditLog
from app.db.models import User
from app.github import client as gh
from app.github import oauth, sync
from app.github.models import GithubConnection, GithubRepo, GithubSkillProposal, GithubSyncRun
from app.gmail.crypto import decrypt_token, encrypt_token

# --- the client's reads ---------------------------------------------------------------------


def _http(fake: FakeGitHub, **kwargs: object) -> tuple[httpx.AsyncClient, gh.GithubHttp]:
    client = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))
    return client, gh.GithubHttp(client, "token", **kwargs)  # type: ignore[arg-type]


async def test_the_repo_list_follows_pages_and_keeps_only_what_it_needs() -> None:
    fake = FakeGitHub()
    page = "/users/me/repos?type=owner&sort=pushed&per_page=100&page="
    fake.routes[f"{page}1"] = ok(
        [repo(1, "a", license={"spdx_id": "MIT"}, topics=["ml"]), {"name": "no-id"}],
        link='<https://api.github.com/x?page=2>; rel="next"',
    )
    fake.routes[f"{page}2"] = ok([repo(2, "b")])
    client, http = _http(fake)

    async with client:
        repos = await gh.list_owned_public_repos(http, "me")

    assert [r["name"] for r in repos] == ["a", "b"]  # the id-less entry is dropped
    assert repos[0]["license_spdx"] == "MIT"
    assert repos[0]["topics"] == ["ml"]
    assert repos[1]["license_spdx"] is None
    assert fake.requests == [f"{page}1", f"{page}2"]


async def test_commit_stats_use_the_link_header_for_the_total_and_two_requests() -> None:
    fake = FakeGitHub()
    fake.project(
        "r", languages={}, commits=43, newest="2026-09-12T00:00:00Z", oldest="2026-03-01T00:00:00Z"
    )
    client, http = _http(fake)

    async with client:
        stats = await gh.get_commit_stats(http, "me/r", "me")

    assert (stats.count, stats.last_at, stats.first_at) == (
        43,
        "2026-09-12T00:00:00Z",
        "2026-03-01T00:00:00Z",
    )
    assert len(fake.requests) == 2


async def test_commit_stats_for_one_none_and_an_empty_repository() -> None:
    fake = FakeGitHub()
    fake.project("one", languages={}, commits=1, newest="2026-05-05T00:00:00Z")
    fake.project("none", languages={}, commits=0)
    fake.routes["/repos/me/empty/commits?author=me&per_page=1"] = ok(
        {"message": "Git Repository is empty."}, status=409
    )
    client, http = _http(fake)

    async with client:
        one = await gh.get_commit_stats(http, "me/one", "me")
        none = await gh.get_commit_stats(http, "me/none", "me")
        empty = await gh.get_commit_stats(http, "me/empty", "me")

    assert (one.count, one.first_at, one.last_at) == (
        1,
        "2026-05-05T00:00:00Z",
        "2026-05-05T00:00:00Z",
    )
    assert none.count == 0
    assert empty.count == 0
    assert len(fake.requests) == 3  # a single commit needs no second request


async def test_the_file_tree_comes_in_one_request_with_its_truncation_flag() -> None:
    fake = FakeGitHub()
    fake.project("r", languages={}, commits=0, files={"backend/requirements.txt": "flask\n"})
    fake.routes["/repos/me/big/git/trees/main?recursive=1"] = ok(
        {"tree": [{"path": "a.txt", "type": "blob"}], "truncated": True}
    )
    fake.routes["/repos/me/empty/git/trees/main?recursive=1"] = ok({"message": "empty"}, status=409)
    fake.routes["/repos/me/gone/git/trees/main?recursive=1"] = ok({"message": "nope"}, status=404)
    fake.routes["/repos/me/odd/git/trees/main?recursive=1"] = ok({"unexpected": True})
    client, http = _http(fake)

    async with client:
        entries, truncated = await gh.list_tree(http, "me/r", "main")
        assert await gh.list_tree(http, "me/big", "main") == ([gh.TreeEntry("a.txt", "blob")], True)
        assert await gh.list_tree(http, "me/empty", "main") == ([], False)
        assert await gh.list_tree(http, "me/gone", "main") == ([], False)
        with pytest.raises(gh.GithubApiError, match="no file list"):
            await gh.list_tree(http, "me/odd", "main")

    assert truncated is False
    assert [(e.path, e.type) for e in entries] == [
        ("README.md", "blob"),
        ("backend", "tree"),
        ("backend/requirements.txt", "blob"),
    ]
    assert fake.requests[0] == "/repos/me/r/git/trees/main?recursive=1"


async def test_text_files_are_read_only_when_small_utf8_and_really_files() -> None:
    fake = FakeGitHub()
    fake.project("r", languages={}, commits=0, files={"backend/requirements.txt": "flask\n"})
    fake.routes["/repos/me/r/contents/big.txt"] = ok(
        {"encoding": "base64", "content": b64("x"), "size": gh.MAX_FILE_BYTES + 1}
    )
    fake.routes["/repos/me/r/contents/bin.dat"] = ok(
        {"encoding": "base64", "content": "/w==", "size": 1}  # 0xFF is not UTF-8
    )
    fake.routes["/repos/me/r/contents/dir"] = ok([{"name": "x"}])  # a folder, not a file
    client, http = _http(fake)

    async with client:
        assert await gh.get_text_file(http, "me/r", "backend/requirements.txt") == "flask\n"
        assert await gh.get_text_file(http, "me/r", "missing.txt") is None
        assert await gh.get_text_file(http, "me/r", "big.txt") is None
        assert await gh.get_text_file(http, "me/r", "bin.dat") is None
        assert await gh.get_text_file(http, "me/r", "dir") is None


def _blob(*paths: str) -> list[gh.TreeEntry]:
    return [gh.TreeEntry(p, "blob") for p in paths]


def test_manifests_are_found_in_subfolders_shallowest_first() -> None:
    entries = _blob(
        "frontend/package.json",
        "requirements.txt",
        "backend/requirements-dev.txt",
        "services/api/pyproject.toml",
        "README.md",
        "docs/notes.txt",
    ) + [gh.TreeEntry("backend", "tree")]

    assert sync.manifest_paths(entries) == [
        "requirements.txt",
        "backend/requirements-dev.txt",
        "frontend/package.json",
        "services/api/pyproject.toml",
    ]


def test_vendored_folders_and_deep_paths_are_not_read_as_your_dependencies() -> None:
    entries = _blob(
        "node_modules/react/package.json",
        "frontend/node_modules/left-pad/package.json",
        ".venv/lib/site-packages/x/requirements.txt",
        "a/b/c/package.json",  # deeper than two folders
        "web/package.json",
    )

    assert sync.manifest_paths(entries) == ["web/package.json"]


def test_a_repo_with_hundreds_of_manifests_reads_only_a_few() -> None:
    entries = _blob(*[f"pkg{i:03d}/package.json" for i in range(300)])

    assert len(sync.manifest_paths(entries)) == sync.MAX_MANIFESTS_PER_REPO


async def test_events_stop_when_there_is_no_next_page() -> None:
    fake = FakeGitHub()
    fake.events("2026-09-10T08:00:00Z")
    client, http = _http(fake)

    async with client:
        events = await gh.list_public_events(http, "me")

    assert len(events) == 1
    assert len(fake.requests) == 1


# --- retries, rate limits and the request budget --------------------------------------------


class _Sleeper:
    def __init__(self) -> None:
        self.waits: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)


async def test_server_errors_are_retried_with_backoff_then_succeed() -> None:
    fake = FakeGitHub()
    answers = iter([httpx.Response(502), httpx.Response(503), ok({"ok": True})])
    fake.routes["/x"] = lambda request: next(answers)
    sleeper = _Sleeper()
    client, http = _http(fake, sleep=sleeper)

    async with client:
        response = await http.get("/x")

    assert response.json() == {"ok": True}
    assert sleeper.waits == [1.0, 2.0]
    assert http.requests_made == 3


async def test_persistent_server_errors_give_up_after_three_attempts() -> None:
    fake = FakeGitHub()
    fake.routes["/x"] = httpx.Response(500)
    client, http = _http(fake, sleep=_Sleeper())

    async with client:
        with pytest.raises(gh.GithubApiError, match="HTTP 500"):
            await http.get("/x")

    assert http.requests_made == 3


async def test_a_short_rate_limit_wait_is_honoured_and_retried() -> None:
    fake = FakeGitHub()
    answers = iter([httpx.Response(403, headers={"retry-after": "3"}), ok({"ok": True})])
    fake.routes["/x"] = lambda request: next(answers)
    sleeper = _Sleeper()
    client, http = _http(fake, sleep=sleeper)

    async with client:
        await http.get("/x")

    assert sleeper.waits == [3.0]


async def test_a_long_rate_limit_wait_is_refused_instead_of_slept_through() -> None:
    fake = FakeGitHub()
    fake.routes["/x"] = httpx.Response(
        403, headers={"x-ratelimit-remaining": "0", "retry-after": "900"}
    )
    sleeper = _Sleeper()
    client, http = _http(fake, sleep=sleeper)

    async with client:
        with pytest.raises(gh.RateLimitedError, match="900s"):
            await http.get("/x")

    assert sleeper.waits == []


async def test_a_429_without_a_hint_counts_as_a_long_wait() -> None:
    fake = FakeGitHub()
    fake.routes["/x"] = httpx.Response(429)
    client, http = _http(fake, sleep=_Sleeper())

    async with client:
        with pytest.raises(gh.RateLimitedError):
            await http.get("/x")


async def test_a_plain_403_is_an_error_not_a_rate_limit_and_is_not_retried() -> None:
    fake = FakeGitHub()
    fake.routes["/x"] = httpx.Response(403, json={"message": "Repository access blocked"})
    client, http = _http(fake, sleep=_Sleeper())

    async with client:
        with pytest.raises(gh.GithubApiError) as caught:
            await http.get("/x")

    assert not isinstance(caught.value, gh.RateLimitedError)
    assert http.requests_made == 1


async def test_a_401_is_an_auth_error() -> None:
    fake = FakeGitHub()
    fake.routes["/x"] = httpx.Response(401)
    client, http = _http(fake)

    async with client:
        with pytest.raises(gh.GithubAuthError):
            await http.get("/x")


async def test_the_request_budget_stops_a_sync_before_it_overspends() -> None:
    fake = FakeGitHub()
    fake.routes["/x"] = ok({})
    client, http = _http(fake, budget=2)

    async with client:
        await http.get("/x")
        await http.get("/x")
        with pytest.raises(gh.RequestBudgetExceededError):
            await http.get("/x")

    assert len(fake.requests) == 2


# --- the sync -------------------------------------------------------------------------------


async def _connection(
    session_factory: async_sessionmaker[AsyncSession], **overrides: object
) -> GithubConnection:
    async with session_factory() as db:
        user = (await db.execute(select(User))).scalars().first()
        if user is None:
            user = User(email="owner@example.com", hashed_password="x")
            db.add(user)
            await db.flush()
        fields: dict[str, object] = {
            "user_id": user.id,
            "github_login": "me",
            "github_user_id": 1,
            "access_token_encrypted": encrypt_token("access-token"),
            "refresh_token_encrypted": encrypt_token("refresh-token"),
            "token_expires_at": datetime.now(UTC) + timedelta(hours=4),
            "installations": [],
            "status": "connected",
            **overrides,
        }
        connection = GithubConnection(**fields)  # type: ignore[arg-type]
        db.add(connection)
        await db.commit()
        return connection


async def _run(
    session_factory: async_sessionmaker[AsyncSession],
    fake: FakeGitHub,
    monkeypatch: pytest.MonkeyPatch,
    connection: GithubConnection,
) -> GithubSyncRun:
    monkeypatch.setattr(sync.httpx, "AsyncClient", fake.client_factory())
    async with session_factory() as db:
        run = await sync.start_run(db, connection.id)
        await sync.run_sync(db, run.id)
    async with session_factory() as db:
        return await db.get(GithubSyncRun, run.id)  # type: ignore[return-value]


async def _proposals(
    session_factory: async_sessionmaker[AsyncSession],
) -> dict[str, GithubSkillProposal]:
    async with session_factory() as db:
        rows = (await db.execute(select(GithubSkillProposal))).scalars().all()
    return {r.skill_name: r for r in rows}


async def test_a_sync_snapshots_repos_and_reads_details_only_for_your_own_active_ones(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeGitHub()
    fake.account()
    connection = await _connection(session_factory)

    run = await _run(session_factory, fake, monkeypatch, connection)

    assert run.status == "completed"
    assert run.error is None
    assert (run.repos_seen, run.repos_detailed) == (5, 3)
    assert run.requests_made == len(fake.requests)
    # Nothing was read for the fork or the archive, beyond the list itself.
    assert not [r for r in fake.requests if "someone-elses-project" in r or "old-experiment" in r]
    async with session_factory() as db:
        repos = {r.name: r for r in (await db.execute(select(GithubRepo))).scalars().all()}
    assert set(repos) == {
        "AegisAI",
        "smart-campus-ai",
        "plant-disease-classifier",
        "someone-elses-project",
        "old-experiment",
    }
    aegis = repos["AegisAI"]
    assert aegis.details_fetched is True
    assert aegis.languages == {"Python": 114_846, "HTML": 62_339}
    assert aegis.authored_commits == 43
    assert aegis.first_commit_at.year == 2026 and aegis.last_commit_at.month == 9  # type: ignore[union-attr]
    assert sorted(aegis.root_files) == [
        "Dockerfile",
        "requirements.txt",
    ]  # no README, like the real repo
    assert {d["skill"] for d in aegis.dependencies} == {"FastAPI", "SQLAlchemy"}
    assert repos["plant-disease-classifier"].authored_commits == 0  # looked up: none attributed
    assert repos["someone-elses-project"].details_fetched is False
    assert repos["someone-elses-project"].is_fork is True
    assert repos["old-experiment"].is_archived is True


async def test_a_sync_proposes_skills_with_their_evidence(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeGitHub()
    fake.account()
    connection = await _connection(session_factory)

    run = await _run(session_factory, fake, monkeypatch, connection)

    proposals = await _proposals(session_factory)
    assert {"Python", "JavaScript", "HTML", "FastAPI", "SQLAlchemy", "React", "Docker"} <= set(
        proposals
    )
    assert "Jupyter Notebooks" in proposals
    python = proposals["Python"]
    assert python.attribution == "attributed"
    assert [c["repo"] for c in python.contributions] == ["AegisAI", "smart-campus-ai"]
    assert python.status == "pending"
    assert proposals["Jupyter Notebooks"].attribution == "ownership_only"
    assert proposals["FastAPI"].kind == "framework"
    assert proposals["FastAPI"].contributions[0]["source_url"].endswith("/requirements.txt")
    assert proposals["Docker"].kind == "tool"
    reasons = {s["subject"]: s["reason"] for s in run.skipped}
    assert "fork" in reasons["someone-elses-project"]
    assert "Archived" in reasons["old-experiment"]
    assert "Only 1.4 KB" in reasons["plant-disease-classifier: Python"]
    assert "CSS" not in proposals  # 2.9 KB in smart-campus-ai: under the threshold
    assert "Only 2.9 KB" in reasons["smart-campus-ai: CSS"]
    assert "isn't counted as Python" in reasons["plant-disease-classifier: Jupyter Notebook"]


async def test_dependencies_in_subfolders_are_found_and_cited_by_their_path(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeGitHub()
    fake.account()

    await _run(session_factory, fake, monkeypatch, await _connection(session_factory))

    proposals = await _proposals(session_factory)
    fastapi = {c["repo"]: c for c in proposals["FastAPI"].contributions}
    assert fastapi["AegisAI"]["source_file"] == "requirements.txt"
    assert fastapi["smart-campus-ai"]["source_file"] == "backend/requirements.txt"
    assert fastapi["smart-campus-ai"]["source_url"] == (
        "https://github.com/me/smart-campus-ai/blob/main/backend/requirements.txt"
    )
    react = proposals["React"].contributions[0]
    assert (react["repo"], react["source_file"]) == ("smart-campus-ai", "frontend/package.json")


async def test_a_truncated_file_list_is_reported_rather_than_hidden(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeGitHub()
    fake.account()
    fake.routes["/repos/me/AegisAI/git/trees/main?recursive=1"] = ok(
        {"tree": [{"path": "requirements.txt", "type": "blob"}], "truncated": True}
    )

    run = await _run(session_factory, fake, monkeypatch, await _connection(session_factory))

    assert run.status == "completed"
    assert any("AegisAI" in w and "cut off its file list" in w for w in run.warnings)


async def test_a_sync_records_what_the_readiness_review_needs_without_keeping_readme_text(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeGitHub()
    fake.account()
    fake.project(
        "smart-campus-ai",
        languages={"JavaScript": 78_123},
        commits=29,
        readme=("# Campus\n\nSecret marketing prose that must not be stored.\n\n## Installation\n"),
        files={
            ".yolov8n-pose.pt.38fb.part": "",
            "tests/test_a.py": "x",
            ".github/workflows/ci.yml": "x",
        },
    )
    connection = await _connection(session_factory)

    await _run(session_factory, fake, monkeypatch, connection)

    async with session_factory() as db:
        repos = {r.name: r for r in (await db.execute(select(GithubRepo))).scalars().all()}
        stored = await db.get(GithubConnection, connection.id)
    aegis, campus = repos["AegisAI"], repos["smart-campus-ai"]
    assert aegis.readme == {"present": False}
    assert campus.readme["present"] is True and campus.readme["structured"] is True  # type: ignore[index]
    assert campus.readme["has_setup_section"] is True  # type: ignore[index]
    assert "marketing prose" not in str(campus.readme)  # structure only, never the text
    assert campus.notable_paths == {
        "tests": ["tests/test_a.py"],
        "ci": [".github/workflows/ci.yml"],
        "secrets": [],
        "junk": [".yolov8n-pose.pt.38fb.part"],
    }
    assert campus.tree_truncated is False
    assert repos["someone-elses-project"].notable_paths is None  # forks aren't read at all
    assert stored.profile_facts == {  # type: ignore[union-attr]
        "login": "me",
        "name": "Aziz Ahmad",
        "bio": "ML engineer building vision systems",
        "company": None,
        "location": "Lahore",
        "blog": "",
        "public_repos": 3,
        "followers": None,
        "created_at": None,
        "hireable": None,
    }


async def test_the_profile_facts_come_from_the_user_call_with_no_extra_request(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeGitHub()
    fake.account()

    await _run(session_factory, fake, monkeypatch, await _connection(session_factory))

    assert fake.requests.count("/user") == 1
    assert not [r for r in fake.requests if r == "/users/me"]


async def test_an_unreadable_readme_is_recorded_as_unreadable_not_as_missing(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeGitHub()
    fake.account()
    fake.routes["/repos/me/smart-campus-ai/contents/README.md"] = ok(
        {"encoding": "base64", "content": "/w==", "size": 1}  # 0xFF is not UTF-8
    )

    await _run(session_factory, fake, monkeypatch, await _connection(session_factory))

    async with session_factory() as db:
        campus = (
            await db.execute(select(GithubRepo).where(GithubRepo.name == "smart-campus-ai"))
        ).scalar_one()
    assert campus.readme["present"] is True  # type: ignore[index]
    assert campus.readme["readable"] is False  # type: ignore[index]
    assert "couldn't be read" in campus.readme["reason"]  # type: ignore[index]


async def test_a_sync_summarizes_recent_activity_and_says_how_far_back_it_sees(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeGitHub()
    fake.account()

    run = await _run(session_factory, fake, monkeypatch, await _connection(session_factory))

    assert run.activity is not None
    assert (run.activity["push_events"], run.activity["active_days"]) == (2, 2)
    assert "90 days" in run.activity["note"]


async def test_a_sync_is_audited_without_any_token(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeGitHub()
    fake.account()

    await _run(session_factory, fake, monkeypatch, await _connection(session_factory))

    async with session_factory() as db:
        entry = (
            await db.execute(select(AuditLog).where(AuditLog.action == "github.synced"))
        ).scalar_one()
    assert entry.risk_level == "green"
    assert entry.evidence["repos_seen"] == 5
    assert "access-token" not in str(entry.evidence) + entry.summary


async def test_an_existing_profile_skill_is_matched_and_keeps_its_name_and_level(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.profile.models import Profile, Skill, SkillVersion

    fake = FakeGitHub()
    fake.account()
    connection = await _connection(session_factory)
    async with session_factory() as db:
        profile = Profile(user_id=connection.user_id)
        db.add(profile)
        await db.flush()
        skill = Skill(profile_id=profile.id, name="python")
        db.add(skill)
        await db.flush()
        db.add(
            SkillVersion(skill_id=skill.id, level="advanced", evidence="Built and shipped things.")
        )
        await db.commit()

    await _run(session_factory, fake, monkeypatch, connection)

    proposals = await _proposals(session_factory)
    assert "Python" not in proposals
    assert proposals["python"].existing_skill_name == "python"
    assert proposals["python"].existing_level == "advanced"


async def test_syncing_again_changes_nothing_and_never_duplicates_proposals(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeGitHub()
    fake.account()
    connection = await _connection(session_factory)
    await _run(session_factory, fake, monkeypatch, connection)
    first = await _proposals(session_factory)

    await _run(session_factory, fake, monkeypatch, connection)

    second = await _proposals(session_factory)
    assert {k: v.id for k, v in first.items()} == {k: v.id for k, v in second.items()}
    async with session_factory() as db:
        assert len((await db.execute(select(GithubRepo))).scalars().all()) == 5


async def test_a_decided_proposal_is_left_alone_but_new_evidence_makes_a_new_one(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeGitHub()
    fake.account()
    connection = await _connection(session_factory)
    await _run(session_factory, fake, monkeypatch, connection)
    async with session_factory() as db:
        html = (
            await db.execute(
                select(GithubSkillProposal).where(GithubSkillProposal.skill_name == "HTML")
            )
        ).scalar_one()
        html.status = "dismissed"
        await db.commit()

    # Same evidence: still dismissed, not re-asked.
    await _run(session_factory, fake, monkeypatch, connection)
    async with session_factory() as db:
        rows = (
            (
                await db.execute(
                    select(GithubSkillProposal).where(GithubSkillProposal.skill_name == "HTML")
                )
            )
            .scalars()
            .all()
        )
    assert [r.status for r in rows] == ["dismissed"]

    # A new repo that also uses HTML is new evidence, so it's a new question.
    fake.repos(
        repo(1, "AegisAI"),
        repo(2, "smart-campus-ai", language="JavaScript"),
        repo(3, "plant-disease-classifier", language="Jupyter Notebook"),
        repo(6, "portfolio", language="HTML"),
    )
    fake.project("portfolio", languages={"HTML": 20_000}, commits=7)
    await _run(session_factory, fake, monkeypatch, connection)
    async with session_factory() as db:
        rows = (
            (
                await db.execute(
                    select(GithubSkillProposal).where(GithubSkillProposal.skill_name == "HTML")
                )
            )
            .scalars()
            .all()
        )
    assert sorted(r.status for r in rows) == ["dismissed", "pending"]


async def test_a_pending_proposal_is_withdrawn_when_its_evidence_disappears(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeGitHub()
    fake.account()
    connection = await _connection(session_factory)
    await _run(session_factory, fake, monkeypatch, connection)
    assert "React" in await _proposals(session_factory)

    # smart-campus-ai went private (or was deleted): it is no longer in the public list.
    fake.repos(repo(1, "AegisAI"), repo(3, "plant-disease-classifier", language="Jupyter Notebook"))
    await _run(session_factory, fake, monkeypatch, connection)

    proposals = await _proposals(session_factory)
    assert "React" not in proposals
    assert "JavaScript" not in proposals
    async with session_factory() as db:
        names = {r.name for r in (await db.execute(select(GithubRepo))).scalars().all()}
    assert names == {"AegisAI", "plant-disease-classifier"}


async def test_one_unreadable_repo_is_reported_and_the_rest_still_sync(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeGitHub()
    fake.account()
    fake.routes["/repos/me/smart-campus-ai/languages"] = httpx.Response(500)
    connection = await _connection(session_factory)
    monkeypatch.setattr(gh, "_pause", _Sleeper())

    run = await _run(session_factory, fake, monkeypatch, connection)

    assert run.status == "completed"
    assert run.repos_detailed == 2
    assert any("smart-campus-ai" in w and "couldn't be read" in w for w in run.warnings)
    async with session_factory() as db:
        broken = (
            await db.execute(select(GithubRepo).where(GithubRepo.name == "smart-campus-ai"))
        ).scalar_one()
    assert broken.details_fetched is False  # never half-read
    assert broken.languages == {}
    reasons = {s["subject"]: s["reason"] for s in run.skipped}
    assert "couldn't be fetched" in reasons["smart-campus-ai"]
    assert "Python" in await _proposals(session_factory)  # from AegisAI alone


async def test_hitting_a_long_rate_limit_stops_early_and_keeps_what_was_read(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeGitHub()
    fake.account()
    fake.routes["/repos/me/smart-campus-ai/languages"] = httpx.Response(
        403, headers={"x-ratelimit-remaining": "0", "retry-after": "900"}
    )

    run = await _run(session_factory, fake, monkeypatch, await _connection(session_factory))

    assert run.status == "completed"
    assert any(w.startswith("Stopped early") and "900s" in w for w in run.warnings)
    async with session_factory() as db:
        names = {
            r.name
            for r in (await db.execute(select(GithubRepo))).scalars().all()
            if r.details_fetched
        }
    assert names == {"AegisAI"}  # smart-campus-ai stopped the loop; the third was never reached


async def test_the_request_budget_cap_is_reported(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeGitHub()
    fake.account()
    monkeypatch.setattr(sync, "MAX_REQUESTS", 8)

    run = await _run(session_factory, fake, monkeypatch, await _connection(session_factory))

    assert run.status == "completed"
    assert any("limit" in w for w in run.warnings)
    assert run.requests_made <= 8


async def test_a_rejected_token_fails_the_run_and_marks_the_connection_needs_reauth(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeGitHub()
    fake.routes["/user"] = httpx.Response(401)
    connection = await _connection(session_factory)

    run = await _run(session_factory, fake, monkeypatch, connection)

    assert run.status == "failed"
    assert "reconnect" in (run.error or "").lower()
    async with session_factory() as db:
        stored = await db.get(GithubConnection, connection.id)
        failed = (
            await db.execute(select(AuditLog).where(AuditLog.action == "github.sync_failed"))
        ).scalar_one()
    assert stored.status == "needs_reauth"  # type: ignore[union-attr]
    assert failed.status == "failed"


async def test_a_disconnected_connection_fails_the_run_without_calling_github(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeGitHub()
    connection = await _connection(
        session_factory, status="disconnected", access_token_encrypted=None
    )

    run = await _run(session_factory, fake, monkeypatch, connection)

    assert run.status == "failed"
    assert "isn't connected" in (run.error or "")
    assert fake.requests == []


async def test_a_renamed_account_is_followed(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeGitHub()
    fake.routes["/user"] = ok({"login": "renamed", "id": 1})
    fake.routes["/users/renamed/repos?type=owner&sort=pushed&per_page=100&page=1"] = ok([])
    fake.routes["/users/renamed/events/public?per_page=100&page=1"] = ok([])
    connection = await _connection(session_factory)

    run = await _run(session_factory, fake, monkeypatch, connection)

    assert run.status == "completed"
    async with session_factory() as db:
        assert (await db.get(GithubConnection, connection.id)).github_login == "renamed"  # type: ignore[union-attr]


async def test_an_access_token_that_is_about_to_expire_is_refreshed_before_syncing(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeGitHub()
    fake.account()
    seen_auth: list[str] = []
    original = fake.handler

    def handler(request: httpx.Request) -> httpx.Response:
        seen_auth.append(request.headers["authorization"])
        return original(request)

    fake.handler = handler  # type: ignore[method-assign]

    async def refresh(refresh_token: str) -> oauth.TokenResponse:
        assert refresh_token == "refresh-token"
        return oauth.TokenResponse(
            "new-access", "new-refresh", datetime.now(UTC) + timedelta(hours=8), None
        )

    monkeypatch.setattr(oauth, "refresh_access_token", refresh)
    connection = await _connection(
        session_factory, token_expires_at=datetime.now(UTC) + timedelta(seconds=10)
    )

    run = await _run(session_factory, fake, monkeypatch, connection)

    assert run.status == "completed"
    assert set(seen_auth) == {"Bearer new-access"}
    async with session_factory() as db:
        stored = await db.get(GithubConnection, connection.id)
        assert decrypt_token(stored.refresh_token_encrypted) == "new-refresh"  # type: ignore[union-attr,arg-type]


async def test_a_failure_in_the_middle_leaves_no_half_written_run(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeGitHub()
    fake.user()
    fake.routes["/users/me/repos?type=owner&sort=pushed&per_page=100&page=1"] = ok(
        {"not": "a list"}
    )

    run = await _run(session_factory, fake, monkeypatch, await _connection(session_factory))

    assert run.status == "failed"
    assert run.completed_at is not None
    assert "not a list" in (run.error or "")


async def test_a_database_failure_mid_sync_is_still_recorded_on_the_run(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    # A failed flush rolls the session back and expires every object in it. The failure path
    # must still be able to mark the run failed, not die reading an expired attribute.
    async def duplicate_rows(
        db: AsyncSession, connection: GithubConnection, drafts: object
    ) -> None:
        for _ in range(2):
            db.add(
                GithubSkillProposal(
                    connection_id=connection.id,
                    skill_name="Dup",
                    kind="language",
                    fingerprint="f",
                    contributions=[],
                    attribution="attributed",
                )
            )
        await db.flush()

    monkeypatch.setattr(sync, "_store_proposals", duplicate_rows)
    fake = FakeGitHub()
    fake.account()

    run = await _run(session_factory, fake, monkeypatch, await _connection(session_factory))

    assert run.status == "failed"
    assert run.completed_at is not None
    assert run.error == "Something went wrong while syncing. Try again."
    async with session_factory() as db:
        assert (await db.execute(select(GithubSkillProposal))).first() is None  # rolled back


def test_a_run_is_active_until_it_is_old_enough_to_presume_dead() -> None:
    now = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)
    fresh = GithubSyncRun(status="running", started_at=now - timedelta(minutes=2))
    old = GithubSyncRun(status="running", started_at=now - timedelta(minutes=11))
    done = GithubSyncRun(status="completed", started_at=now - timedelta(minutes=30))

    assert sync.is_active(fresh, now=now) and not sync.is_stalled(fresh, now=now)
    assert sync.is_stalled(old, now=now) and not sync.is_active(old, now=now)
    assert not sync.is_active(done, now=now) and not sync.is_stalled(done, now=now)


def test_link_helper_matches_what_the_client_parses() -> None:
    assert 'rel="last"' in link(43, "/repos/me/r/commits?author=me&per_page=1")
    assert commit("2026-01-01T00:00:00Z")["commit"]["author"]["date"] == "2026-01-01T00:00:00Z"
