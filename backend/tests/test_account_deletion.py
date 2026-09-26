"""The genuine "delete all my data" red-risk action (app.auth.account_deletion), distinct
from each integration's own per-connection disconnect-and-purge. All revoke calls are
stubbed — no test reaches a real provider."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth import account_deletion
from app.career.models import JobPosting
from app.db.models import User
from app.gmail.crypto import encrypt_token
from app.gmail.models import GmailConnection
from app.research.models import ResearchQuery


async def _user_id(session_factory: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    async with session_factory() as db:
        result = await db.execute(select(User).where(User.email == "profile-owner@example.com"))
        return result.scalar_one().id


async def _seed_owned_data(
    session_factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID
) -> None:
    async with session_factory() as db:
        db.add(
            JobPosting(user_id=user_id, source_channel="manual", title="Backend Engineer")
        )
        db.add(ResearchQuery(user_id=user_id, query_text="does acme sponsor visas"))
        db.add(
            GmailConnection(
                user_id=user_id,
                google_email="aziz@gmail.com",
                access_token_encrypted=encrypt_token("access"),
                refresh_token_encrypted=encrypt_token("refresh"),
                token_expires_at=datetime.now(UTC) + timedelta(hours=1),
                granted_scopes="https://www.googleapis.com/auth/gmail.readonly",
                status="connected",
            )
        )
        await db.commit()


def _fake_revocations(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[str]]:
    revoked: dict[str, list[str]] = {"gmail": [], "calendar": [], "github": []}

    async def revoke(kind: str, token: str) -> bool:
        revoked[kind].append(token)
        return True

    monkeypatch.setattr(
        account_deletion.gmail_oauth, "revoke_token", lambda t: revoke("gmail", t)
    )
    monkeypatch.setattr(
        account_deletion.calendar_oauth, "revoke_token", lambda t: revoke("calendar", t)
    )
    monkeypatch.setattr(
        account_deletion.github_oauth, "revoke_token", lambda t: revoke("github", t)
    )
    return revoked


async def test_request_files_a_pending_red_action_with_a_live_evidence_snapshot(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    user_id = await _user_id(session_factory)
    await _seed_owned_data(session_factory, user_id)

    response = await client.post("/auth/delete-account/request", headers=auth_headers)

    assert response.status_code == 201
    body = response.json()
    assert body["risk_level"] == "red"
    assert body["status"] == "pending_approval"
    assert body["evidence"]["row_counts"]["job_postings"] == 1
    assert body["evidence"]["row_counts"]["research_queries"] == 1
    assert body["evidence"]["connections"]["gmail"] == "connected"
    assert body["evidence"]["connections"]["github"] == "not_connected"


async def test_declining_leaves_the_account_and_its_data_untouched(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_revocations(monkeypatch)
    user_id = await _user_id(session_factory)
    await _seed_owned_data(session_factory, user_id)

    request_response = await client.post("/auth/delete-account/request", headers=auth_headers)
    log_id = request_response.json()["id"]

    response = await client.post(
        f"/auth/delete-account/{log_id}/decide",
        headers=auth_headers,
        json={"approved": False},
    )

    assert response.status_code == 200
    assert response.json() == {"deleted": False, "row_counts": None, "revoked_at_provider": None}

    async with session_factory() as db:
        assert await db.get(User, user_id) is not None
        postings = (
            await db.execute(select(JobPosting).where(JobPosting.user_id == user_id))
        ).scalars().all()
        assert len(postings) == 1


async def test_approving_deletes_the_user_and_cascades_every_owned_row(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    revoked = _fake_revocations(monkeypatch)
    user_id = await _user_id(session_factory)
    await _seed_owned_data(session_factory, user_id)

    request_response = await client.post("/auth/delete-account/request", headers=auth_headers)
    log_id = request_response.json()["id"]

    response = await client.post(
        f"/auth/delete-account/{log_id}/decide",
        headers=auth_headers,
        json={"approved": True},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["deleted"] is True
    assert body["row_counts"]["job_postings"] == 1
    assert body["row_counts"]["research_queries"] == 1
    assert body["revoked_at_provider"] == {"gmail": True}
    assert revoked["gmail"] == ["refresh"]  # refresh token preferred — kills the whole grant

    async with session_factory() as db:
        assert await db.get(User, user_id) is None
        assert (
            await db.execute(select(JobPosting).where(JobPosting.user_id == user_id))
        ).first() is None
        assert (
            await db.execute(select(ResearchQuery).where(ResearchQuery.user_id == user_id))
        ).first() is None
        assert (
            await db.execute(select(GmailConnection).where(GmailConnection.user_id == user_id))
        ).first() is None


async def test_the_deleted_users_token_no_longer_authenticates(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_revocations(monkeypatch)
    request_response = await client.post("/auth/delete-account/request", headers=auth_headers)
    log_id = request_response.json()["id"]
    await client.post(
        f"/auth/delete-account/{log_id}/decide", headers=auth_headers, json={"approved": True}
    )

    response = await client.get("/auth/me", headers=auth_headers)

    assert response.status_code == 401


async def test_drifted_evidence_fails_the_second_check_and_deletes_nothing(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A row added between request and decide (e.g. a scheduled feed poll) must make the
    independent second check refuse the approval — never delete against stale evidence."""
    _fake_revocations(monkeypatch)
    user_id = await _user_id(session_factory)

    request_response = await client.post("/auth/delete-account/request", headers=auth_headers)
    log_id = request_response.json()["id"]

    async with session_factory() as db:
        db.add(JobPosting(user_id=user_id, source_channel="manual", title="New posting"))
        await db.commit()

    response = await client.post(
        f"/auth/delete-account/{log_id}/decide",
        headers=auth_headers,
        json={"approved": True},
    )

    assert response.status_code == 409
    async with session_factory() as db:
        assert await db.get(User, user_id) is not None
        assert (
            await db.execute(select(JobPosting).where(JobPosting.user_id == user_id))
        ).first() is not None


async def test_deciding_an_unknown_request_is_409(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.post(
        f"/auth/delete-account/{uuid.uuid4()}/decide",
        headers=auth_headers,
        json={"approved": True},
    )

    assert response.status_code == 409
