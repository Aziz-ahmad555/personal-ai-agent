"""Sync, repos and skill-evidence proposals through the API: the only path by which GitHub data
reaches the profile is the user accepting a proposal."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from github_fake import FakeGitHub
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.models import AuditLog
from app.auth.security import hash_password
from app.db.models import User
from app.github import sync
from app.github.derive import Contribution, evidence_text
from app.github.models import GithubConnection, GithubRepo, GithubSkillProposal, GithubSyncRun
from app.gmail.crypto import encrypt_token

OWNER = "profile-owner@example.com"


async def _connect(
    session_factory: async_sessionmaker[AsyncSession], email: str = OWNER, **overrides: object
) -> uuid.UUID:
    async with session_factory() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one()
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
        return connection.id


async def _sync(
    client: AsyncClient,
    headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    fake: FakeGitHub | None = None,
) -> dict:
    fake = fake or FakeGitHub()
    if not fake.routes:
        fake.account()
    monkeypatch.setattr(sync.httpx, "AsyncClient", fake.client_factory())
    response = await client.post("/github/sync", headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


async def _proposals(client: AsyncClient, headers: dict[str, str]) -> dict[str, dict]:
    response = await client.get("/github/proposals", headers=headers)
    assert response.status_code == 200
    return {p["skill_name"]: p for p in response.json()}


@pytest.fixture
async def synced(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, dict]:
    await _connect(session_factory)
    await _sync(client, auth_headers, monkeypatch)
    return await _proposals(client, auth_headers)


# --- starting a sync ------------------------------------------------------------------------


async def test_every_endpoint_requires_auth(client: AsyncClient) -> None:
    for method, path in (
        ("post", "/github/sync"),
        ("get", "/github/sync"),
        ("get", "/github/repos"),
        ("get", "/github/proposals"),
        ("post", f"/github/proposals/{uuid.uuid4()}/accept"),
        ("post", f"/github/proposals/{uuid.uuid4()}/dismiss"),
    ):
        response = await getattr(client, method)(path)
        assert response.status_code == 401, path


async def test_nothing_works_before_github_is_connected(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    for method, path in (
        ("post", "/github/sync"),
        ("get", "/github/sync"),
        ("get", "/github/repos"),
        ("get", "/github/proposals"),
    ):
        response = await getattr(client, method)(path, headers=auth_headers)
        assert response.status_code == 404, path


async def test_a_sync_needs_a_working_connection(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _connect(session_factory, status="needs_reauth")

    response = await client.post("/github/sync", headers=auth_headers)

    assert response.status_code == 409
    assert "connect or reconnect" in response.json()["detail"]


async def test_a_sync_runs_and_reports_its_results(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _connect(session_factory)

    started = await _sync(client, auth_headers, monkeypatch)

    assert started["status"] in ("pending", "running", "completed")
    runs = (await client.get("/github/sync", headers=auth_headers)).json()
    assert [r["status"] for r in runs] == ["completed"]
    assert (runs[0]["repos_seen"], runs[0]["repos_detailed"]) == (5, 3)
    assert runs[0]["activity"]["push_events"] == 2
    assert runs[0]["error"] is None


async def test_a_second_sync_is_refused_while_one_is_running(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    connection_id = await _connect(session_factory)
    async with session_factory() as db:
        db.add(GithubSyncRun(connection_id=connection_id, status="running"))
        await db.commit()

    response = await client.post("/github/sync", headers=auth_headers)

    assert response.status_code == 409
    assert "already running" in response.json()["detail"]


async def test_an_orphaned_run_is_reported_failed_and_does_not_block_a_new_sync(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection_id = await _connect(session_factory)
    async with session_factory() as db:
        db.add(
            GithubSyncRun(
                connection_id=connection_id,
                status="running",
                started_at=datetime.now(UTC) - timedelta(minutes=30),
            )
        )
        await db.commit()

    runs = (await client.get("/github/sync", headers=auth_headers)).json()
    assert runs[0]["status"] == "failed"
    assert "server was probably restarted" in runs[0]["error"]

    await _sync(client, auth_headers, monkeypatch)  # a new sync is allowed


# --- repos ----------------------------------------------------------------------------------


async def test_repos_are_listed_newest_first_with_flags_and_attributed_commits(
    client: AsyncClient, auth_headers: dict[str, str], synced: dict[str, dict]
) -> None:
    repos = (await client.get("/github/repos", headers=auth_headers)).json()

    by_name = {r["name"]: r for r in repos}
    assert repos[0]["name"] != "smart-campus-ai"  # pushed 09-12 beats 08-31
    assert by_name["someone-elses-project"]["is_fork"] is True
    assert by_name["old-experiment"]["is_archived"] is True
    assert by_name["AegisAI"]["authored_commits"] == 43
    assert by_name["plant-disease-classifier"]["authored_commits"] == 0
    assert by_name["someone-elses-project"]["authored_commits"] is None  # not looked up
    assert by_name["AegisAI"]["html_url"] == "https://github.com/me/AegisAI"
    assert "token" not in str(repos).lower()


# --- proposals ------------------------------------------------------------------------------


async def test_proposals_show_evidence_and_the_exact_text_that_would_be_saved(
    synced: dict[str, dict],
) -> None:
    python = synced["Python"]

    assert python["status"] == "pending"
    assert python["kind"] == "language"
    assert python["attribution"] == "attributed"
    assert python["requires_level"] is True  # a new skill: the user must choose
    assert [c["repo"] for c in python["contributions"]] == ["AegisAI", "smart-campus-ai"]
    assert python["evidence_preview"] == (
        "GitHub (@me): Python — "
        "AegisAI (114.8 KB of Python; 43 commits by this account, last 2026-09-12); "
        "smart-campus-ai (53.8 KB of Python; 29 commits by this account, last 2026-08-31)."
    )
    ownership = synced["Jupyter Notebooks"]
    assert ownership["attribution"] == "ownership_only"
    assert "no commits attributed to it" in ownership["evidence_preview"]


async def test_attributed_proposals_are_listed_before_ownership_only_ones(
    synced: dict[str, dict],
) -> None:
    order = list(synced)

    assert order.index("Python") < order.index("Jupyter Notebooks")


# --- accepting ------------------------------------------------------------------------------


async def _skills(client: AsyncClient, headers: dict[str, str]) -> list[dict]:
    return (await client.get("/profile/skills", headers=headers)).json()


async def test_a_new_skill_cannot_be_accepted_without_choosing_a_level(
    client: AsyncClient, auth_headers: dict[str, str], synced: dict[str, dict]
) -> None:
    response = await client.post(
        f"/github/proposals/{synced['Python']['id']}/accept", headers=auth_headers, json={}
    )

    assert response.status_code == 422
    assert "Choose your level for Python" in response.json()["detail"]
    assert await _skills(client, auth_headers) == []  # nothing was written
    assert (await _proposals(client, auth_headers))["Python"]["status"] == "pending"


async def test_an_invalid_level_is_rejected(
    client: AsyncClient, auth_headers: dict[str, str], synced: dict[str, dict]
) -> None:
    response = await client.post(
        f"/github/proposals/{synced['Python']['id']}/accept",
        headers=auth_headers,
        json={"level": "wizard"},
    )

    assert response.status_code == 422
    assert await _skills(client, auth_headers) == []


async def test_accepting_creates_the_skill_with_the_previewed_evidence_and_audits_it(
    client: AsyncClient,
    auth_headers: dict[str, str],
    synced: dict[str, dict],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    python = synced["Python"]

    response = await client.post(
        f"/github/proposals/{python['id']}/accept",
        headers=auth_headers,
        json={"level": "intermediate"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["proposal"]["status"] == "accepted"
    skills = await _skills(client, auth_headers)
    assert [s["name"] for s in skills] == ["Python"]
    assert skills[0]["category"] == "Language"
    version = skills[0]["versions"][0]
    assert version["level"] == "intermediate"
    assert version["evidence"] == python["evidence_preview"]  # exactly what was shown
    assert version["evidence_url"] == "https://github.com/me/AegisAI"
    assert version["id"] == body["skill_version_id"]

    async with session_factory() as db:
        entry = (
            await db.execute(
                select(AuditLog).where(AuditLog.action == "github.skill_evidence.accept")
            )
        ).scalar_one()
    assert (entry.risk_level, entry.status) == ("yellow", "completed")  # asked, approved, done
    assert entry.decided_at is not None
    assert entry.evidence["level"] == "intermediate"
    assert entry.evidence["level_carried_forward"] is False
    assert entry.result["skill_version_id"] == body["skill_version_id"]


async def test_a_dependency_becomes_a_framework_skill_with_the_file_as_evidence(
    client: AsyncClient, auth_headers: dict[str, str], synced: dict[str, dict]
) -> None:
    fastapi = synced["FastAPI"]

    await client.post(
        f"/github/proposals/{fastapi['id']}/accept",
        headers=auth_headers,
        json={"level": "advanced"},
    )

    skill = (await _skills(client, auth_headers))[0]
    assert skill["category"] == "Framework / library"
    assert skill["versions"][0]["evidence_url"].endswith("/requirements.txt")
    assert "declared in requirements.txt" in skill["versions"][0]["evidence"]


async def test_an_existing_skill_keeps_its_level_unless_the_user_chooses_another(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _connect(session_factory)
    made = await client.post("/profile/skills", headers=auth_headers, json={"name": "python"})
    await client.post(
        f"/profile/skills/{made.json()['id']}/versions",
        headers=auth_headers,
        json={"level": "advanced", "evidence": "Shipped several Python services."},
    )
    await _sync(client, auth_headers, monkeypatch)
    proposals = await _proposals(client, auth_headers)
    assert proposals["python"]["requires_level"] is False
    assert proposals["python"]["existing_level"] == "advanced"

    accepted = await client.post(
        f"/github/proposals/{proposals['python']['id']}/accept", headers=auth_headers, json={}
    )

    assert accepted.status_code == 200
    skills = await _skills(client, auth_headers)
    assert [s["name"] for s in skills] == ["python"]  # merged into the existing skill
    assert [v["level"] for v in skills[0]["versions"]] == ["advanced", "advanced"]  # history kept
    assert any(v["evidence"].startswith("GitHub (@me): python —") for v in skills[0]["versions"])

    other = proposals["HTML"]
    override = await client.post(
        f"/github/proposals/{other['id']}/accept", headers=auth_headers, json={"level": "beginner"}
    )
    assert override.status_code == 200


async def test_a_decided_proposal_cannot_be_decided_again(
    client: AsyncClient, auth_headers: dict[str, str], synced: dict[str, dict]
) -> None:
    proposal_id = synced["Python"]["id"]
    await client.post(
        f"/github/proposals/{proposal_id}/accept", headers=auth_headers, json={"level": "expert"}
    )

    again = await client.post(
        f"/github/proposals/{proposal_id}/accept", headers=auth_headers, json={"level": "expert"}
    )
    dismiss = await client.post(f"/github/proposals/{proposal_id}/dismiss", headers=auth_headers)

    assert again.status_code == 409
    assert dismiss.status_code == 409
    assert "already accepted" in again.json()["detail"]
    versions = (await _skills(client, auth_headers))[0]["versions"]
    assert len(versions) == 1  # accepting twice never doubles the evidence


# --- dismissing -----------------------------------------------------------------------------


async def test_dismissing_changes_nothing_in_the_profile_and_is_audited_as_rejected(
    client: AsyncClient,
    auth_headers: dict[str, str],
    synced: dict[str, dict],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = await client.post(
        f"/github/proposals/{synced['HTML']['id']}/dismiss", headers=auth_headers
    )

    assert response.status_code == 200
    assert response.json()["status"] == "dismissed"
    assert await _skills(client, auth_headers) == []
    async with session_factory() as db:
        entry = (
            await db.execute(
                select(AuditLog).where(AuditLog.action == "github.skill_evidence.accept")
            )
        ).scalar_one()
    assert entry.status == "rejected"
    assert entry.risk_level == "yellow"

    await _sync(client, auth_headers, monkeypatch)  # syncing again doesn't bring it back
    assert (await _proposals(client, auth_headers))["HTML"]["status"] == "dismissed"


async def test_decided_proposals_sort_after_pending_ones(
    client: AsyncClient, auth_headers: dict[str, str], synced: dict[str, dict]
) -> None:
    await client.post(f"/github/proposals/{synced['Python']['id']}/dismiss", headers=auth_headers)

    order = list((await _proposals(client, auth_headers)).values())

    assert order[-1]["status"] == "dismissed"
    assert all(p["status"] == "pending" for p in order[:-1])


# --- withdrawn evidence and isolation -------------------------------------------------------


async def test_accepting_after_the_evidence_went_away_is_a_404_not_a_stale_write(
    client: AsyncClient,
    auth_headers: dict[str, str],
    synced: dict[str, dict],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    react_id = synced["React"]["id"]
    fake = FakeGitHub()
    fake.account()
    fake.repos(*[])  # every repo went private or was deleted
    await _sync(client, auth_headers, monkeypatch, fake)

    response = await client.post(
        f"/github/proposals/{react_id}/accept", headers=auth_headers, json={"level": "beginner"}
    )

    assert response.status_code == 404
    assert await _skills(client, auth_headers) == []


async def test_another_users_proposals_are_invisible_and_untouchable(
    client: AsyncClient,
    auth_headers: dict[str, str],
    synced: dict[str, dict],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as db:
        db.add(User(email="other@example.com", hashed_password=hash_password("x-y-z-123456")))
        await db.commit()
    other_connection = await _connect(
        session_factory, email="other@example.com", github_login="you"
    )
    async with session_factory() as db:
        foreign = GithubSkillProposal(
            connection_id=other_connection,
            skill_name="Go",
            kind="language",
            fingerprint="f" * 32,
            contributions=[],
            attribution="attributed",
        )
        db.add(foreign)
        await db.commit()
        foreign_id = foreign.id

    accept = await client.post(
        f"/github/proposals/{foreign_id}/accept", headers=auth_headers, json={"level": "expert"}
    )
    dismiss = await client.post(f"/github/proposals/{foreign_id}/dismiss", headers=auth_headers)

    assert accept.status_code == 404
    assert dismiss.status_code == 404
    assert "Go" not in await _proposals(client, auth_headers)
    async with session_factory() as db:
        assert (await db.get(GithubSkillProposal, foreign_id)).status == "pending"  # type: ignore[union-attr]


# --- disconnecting --------------------------------------------------------------------------


async def test_disconnect_can_delete_synced_data_but_never_the_skills_you_accepted(
    client: AsyncClient,
    auth_headers: dict[str, str],
    synced: dict[str, dict],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.github import oauth

    async def revoke(token: str) -> bool:
        return True

    monkeypatch.setattr(oauth, "revoke_token", revoke)
    await client.post(
        f"/github/proposals/{synced['Python']['id']}/accept",
        headers=auth_headers,
        json={"level": "advanced"},
    )

    response = await client.delete("/github/connection?purge_data=true", headers=auth_headers)

    assert response.status_code == 200
    async with session_factory() as db:
        assert (await db.execute(select(GithubRepo))).first() is None
        assert (await db.execute(select(GithubSkillProposal))).first() is None
        assert (await db.execute(select(GithubSyncRun))).first() is None
        entry = (
            await db.execute(select(AuditLog).where(AuditLog.action == "github.disconnected"))
        ).scalar_one()
    assert entry.evidence["purged_synced_data"] is True
    assert [s["name"] for s in await _skills(client, auth_headers)] == ["Python"]  # yours, kept


async def test_disconnect_keeps_synced_data_by_default(
    client: AsyncClient,
    auth_headers: dict[str, str],
    synced: dict[str, dict],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.github import oauth

    async def revoke(token: str) -> bool:
        return True

    monkeypatch.setattr(oauth, "revoke_token", revoke)

    await client.delete("/github/connection", headers=auth_headers)

    async with session_factory() as db:
        assert len((await db.execute(select(GithubRepo))).scalars().all()) == 5
    assert (await client.post("/github/sync", headers=auth_headers)).status_code == 409


# --- the evidence sentence ------------------------------------------------------------------


def test_a_very_long_evidence_sentence_is_cut_at_whole_repositories() -> None:
    contributions = [
        Contribution(
            repo=f"repository-number-{i:03d}",
            repo_url=f"https://github.com/me/r{i}",
            via="language",
            source_url=f"https://github.com/me/r{i}",
            source_file=None,
            bytes=10_000,
            commits=5,
            last_commit_at="2026-09-01T00:00:00Z",
            attribution="attributed",
        )
        for i in range(80)
    ]

    text = evidence_text("me", "Python", contributions, limit=1_000)

    assert len(text) <= 1_000
    assert text.startswith("GitHub (@me): Python — repository-number-000")
    assert text.endswith(" more.")
    assert "repository-number-079" not in text
