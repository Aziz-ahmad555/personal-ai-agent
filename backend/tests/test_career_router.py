"""API-level tests, driven through the client the same way test_research_pipeline.py
drives /research/queries — discovery's own fetch/LLM/board calls are faked so nothing
hits the real network."""

import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.security import create_token
from app.career import discovery as discovery_module
from app.career.boards import RawPosting
from app.db.models import User
from app.research.fetch import FetchResult

JOB_URL = "https://acme.example.com/careers/ml-engineer"
JOB_CONTENT = (
    "Acme Corp is hiring a Senior ML Engineer, fully remote, $150,000-$190,000 USD. "
) * 5


class _FakeLLMProvider:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    async def generate_structured(self, **kwargs: object) -> dict[str, object]:
        return self._payload


async def test_create_from_url_then_list_and_get(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_fetch_source(url: str, *, timeout_seconds: float, max_chars: int) -> FetchResult:
        return FetchResult(
            final_url=JOB_URL, http_status=200, content=JOB_CONTENT, title="ML Engineer",
            published_at=datetime(2026, 9, 1, tzinfo=UTC), fetch_error=None,
        )

    llm = _FakeLLMProvider(
        {"title": "Senior ML Engineer", "company_name": "Acme Corp", "remote_type": "remote"}
    )
    monkeypatch.setattr(discovery_module, "fetch_source", fake_fetch_source)
    monkeypatch.setattr(discovery_module, "get_llm_provider", lambda settings: llm)

    create = await client.post(
        "/career/jobs/from-url", headers=auth_headers, json={"url": JOB_URL}
    )
    assert create.status_code == 201
    job_id = create.json()["id"]
    assert create.json()["company_name"] == "Acme Corp"

    listed = await client.get("/career/jobs", headers=auth_headers)
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    got = await client.get(f"/career/jobs/{job_id}", headers=auth_headers)
    assert got.status_code == 200
    assert got.json()["title"] == "Senior ML Engineer"


async def test_create_from_url_returns_502_on_fetch_failure(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_fetch_source(url: str, *, timeout_seconds: float, max_chars: int) -> FetchResult:
        return FetchResult(
            final_url=url, http_status=404, content=None, title=None, published_at=None,
            fetch_error="http_404",
        )

    monkeypatch.setattr(discovery_module, "fetch_source", fake_fetch_source)

    response = await client.post(
        "/career/jobs/from-url", headers=auth_headers, json={"url": "https://dead.example.com/x"}
    )
    assert response.status_code == 502


async def test_create_from_paste(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    llm = _FakeLLMProvider({"remote_type": "onsite", "title": "Warehouse Associate"})
    monkeypatch.setattr(discovery_module, "get_llm_provider", lambda settings: llm)

    response = await client.post(
        "/career/jobs/paste", headers=auth_headers, json={"raw_text": "Pasted job text here."}
    )
    assert response.status_code == 201
    assert response.json()["title"] == "Warehouse Associate"
    assert response.json()["source_channel"] == "manual_paste"


async def test_delete_job_removes_it(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    llm = _FakeLLMProvider({"remote_type": "unknown"})
    monkeypatch.setattr(discovery_module, "get_llm_provider", lambda settings: llm)

    create = await client.post(
        "/career/jobs/paste", headers=auth_headers, json={"raw_text": "text"}
    )
    job_id = create.json()["id"]

    delete = await client.delete(f"/career/jobs/{job_id}", headers=auth_headers)
    assert delete.status_code == 204

    got = await client.get(f"/career/jobs/{job_id}", headers=auth_headers)
    assert got.status_code == 404


async def test_job_from_another_user_is_not_visible(
    client: AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    llm = _FakeLLMProvider({"remote_type": "unknown"})
    monkeypatch.setattr(discovery_module, "get_llm_provider", lambda settings: llm)

    create = await client.post(
        "/career/jobs/paste", headers=auth_headers, json={"raw_text": "text"}
    )
    job_id = create.json()["id"]

    # Registration is single-user/bootstrap-only (see app.auth.router), so a second user
    # for this ownership check is inserted directly, the same way test_gmail_sync.py does.
    async with session_factory() as db:
        other = User(email=f"other-career-{uuid.uuid4()}@example.com", hashed_password="x")
        db.add(other)
        await db.commit()
        other_token = create_token(other.id, "access")

    other_headers = {"Authorization": f"Bearer {other_token}"}
    got = await client.get(f"/career/jobs/{job_id}", headers=other_headers)
    assert got.status_code == 404


async def test_feed_crud_and_validation(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    invalid = await client.post(
        "/career/jobs/feeds", headers=auth_headers, json={"board": "greenhouse"}
    )
    assert invalid.status_code == 422

    create = await client.post(
        "/career/jobs/feeds",
        headers=auth_headers,
        json={"board": "greenhouse", "company_slug": "acme"},
    )
    assert create.status_code == 201
    feed_id = create.json()["id"]

    listed = await client.get("/career/jobs/feeds", headers=auth_headers)
    assert listed.status_code == 200
    assert isinstance(listed.json(), list)
    assert len(listed.json()) == 1

    delete = await client.delete(f"/career/jobs/feeds/{feed_id}", headers=auth_headers)
    assert delete.status_code == 204


async def test_verify_endpoint_dispatches_to_verification_and_returns_202(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Router-level: checks ownership enforcement, the 202 response, and that the
    background task is dispatched with the right job id — the verification/fraud logic
    itself (verified/unconfirmed/suspicious, signal detection) is covered in
    test_career_verification.py and test_career_fraud.py, not re-tested here."""
    llm = _FakeLLMProvider({"remote_type": "unknown"})
    monkeypatch.setattr(discovery_module, "get_llm_provider", lambda settings: llm)

    create = await client.post(
        "/career/jobs/paste", headers=auth_headers, json={"raw_text": "text"}
    )
    job_id = create.json()["id"]

    from app.career import router as career_router_module

    calls: list[tuple[uuid.UUID, uuid.UUID]] = []

    async def fake_verify_and_assess_job(
        db: object, job_posting_id: uuid.UUID, *, user_id: uuid.UUID
    ) -> None:
        calls.append((job_posting_id, user_id))

    monkeypatch.setattr(
        career_router_module, "verify_and_assess_job", fake_verify_and_assess_job
    )

    response = await client.post(f"/career/jobs/{job_id}/verify", headers=auth_headers)
    assert response.status_code == 202
    assert len(calls) == 1
    assert str(calls[0][0]) == job_id


async def test_verify_endpoint_404s_for_another_users_job(
    client: AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    llm = _FakeLLMProvider({"remote_type": "unknown"})
    monkeypatch.setattr(discovery_module, "get_llm_provider", lambda settings: llm)

    create = await client.post(
        "/career/jobs/paste", headers=auth_headers, json={"raw_text": "text"}
    )
    job_id = create.json()["id"]

    async with session_factory() as db:
        other = User(email=f"other-verify-{uuid.uuid4()}@example.com", hashed_password="x")
        db.add(other)
        await db.commit()
        other_token = create_token(other.id, "access")

    response = await client.post(
        f"/career/jobs/{job_id}/verify", headers={"Authorization": f"Bearer {other_token}"}
    )
    assert response.status_code == 404


async def test_poll_feed_endpoint_discovers_new_postings(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_fetch_greenhouse(client_obj: object, company_slug: str) -> list[RawPosting]:
        return [
            RawPosting(
                external_id="42", title="Platform Engineer", location="Remote",
                url="https://acme.example.com/jobs/42", posted_at=None,
                description="Build platforms.", raw={},
            )
        ]

    monkeypatch.setattr(discovery_module, "fetch_greenhouse_postings", fake_fetch_greenhouse)

    create = await client.post(
        "/career/jobs/feeds",
        headers=auth_headers,
        json={"board": "greenhouse", "company_slug": "acme"},
    )
    feed_id = create.json()["id"]

    poll = await client.post(f"/career/jobs/feeds/{feed_id}/poll", headers=auth_headers)
    assert poll.status_code == 202

    jobs = await client.get("/career/jobs", headers=auth_headers)
    titles = [j["title"] for j in jobs.json()]
    assert "Platform Engineer" in titles

    feeds = await client.get("/career/jobs/feeds", headers=auth_headers)
    assert feeds.status_code == 200
    assert feeds.json()[0]["last_polled_at"] is not None
