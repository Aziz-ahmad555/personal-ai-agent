"""Discovery service tests with fetch/LLM/board calls faked (mirrors
test_research_pipeline.py's approach) — no real network or LLM calls. Covers manual
capture's extraction + dedup, and board polling's dedup (by external id and by
description hash across channels) and failure handling."""

import types
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.career import discovery as discovery_module
from app.career.boards import BoardApiError, RawPosting
from app.career.discovery import (
    DiscoveryError,
    capture_job_from_text,
    capture_job_from_url,
    poll_company_feed,
)
from app.career.models import JobBoardFeed, JobPosting
from app.db.models import User
from app.research.fetch import FetchResult

JOB_URL = "https://acme.example.com/careers/ml-engineer"
JOB_CONTENT = (
    "Acme Corp is hiring a Senior ML Engineer, fully remote, $150,000-$190,000 USD. "
) * 5


def _fake_settings(**overrides: object) -> types.SimpleNamespace:
    base: dict[str, object] = {
        "research_fetch_timeout_seconds": 5.0,
        "research_max_content_chars": 20_000,
        "usajobs_api_key": None,
        "usajobs_user_agent_email": None,
    }
    base.update(overrides)
    return types.SimpleNamespace(**base)


class _FakeLLMProvider:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload
        self.calls = 0

    async def generate_structured(self, **kwargs: object) -> dict[str, object]:
        self.calls += 1
        return self._payload


async def _make_user(db: AsyncSession) -> User:
    user = User(email=f"career-test-{uuid.uuid4()}@example.com", hashed_password="x")
    db.add(user)
    await db.flush()
    return user


async def test_capture_job_from_url_extracts_fields_and_dedupes(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_fetch_source(url: str, *, timeout_seconds: float, max_chars: int) -> FetchResult:
        return FetchResult(
            final_url=JOB_URL,
            http_status=200,
            content=JOB_CONTENT,
            title="ML Engineer",
            published_at=datetime(2026, 9, 1, tzinfo=UTC),
            fetch_error=None,
        )

    llm = _FakeLLMProvider(
        {
            "title": "Senior ML Engineer",
            "company_name": "Acme Corp",
            "location": "Remote",
            "remote_type": "remote",
            "salary_min": 150000,
            "salary_max": 190000,
            "salary_currency": "USD",
        }
    )
    monkeypatch.setattr(discovery_module, "fetch_source", fake_fetch_source)
    monkeypatch.setattr(discovery_module, "get_llm_provider", lambda settings: llm)

    async with session_factory() as db:
        user = await _make_user(db)
        settings = _fake_settings()

        posting = await capture_job_from_url(db, user_id=user.id, url=JOB_URL, settings=settings)
        await db.commit()

        assert posting.company_name == "Acme Corp"
        assert posting.title == "Senior ML Engineer"
        assert posting.remote_type == "remote"
        assert posting.salary_min == 150000
        assert posting.research_source_id is not None
        assert llm.calls == 1

        # A second capture of the same URL must not re-fetch or re-extract.
        again = await capture_job_from_url(db, user_id=user.id, url=JOB_URL, settings=settings)
        assert again.id == posting.id
        assert llm.calls == 1


async def test_capture_job_from_url_raises_when_fetch_fails(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_fetch_source(url: str, *, timeout_seconds: float, max_chars: int) -> FetchResult:
        return FetchResult(
            final_url=url,
            http_status=404,
            content=None,
            title=None,
            published_at=None,
            fetch_error="http_404",
        )

    monkeypatch.setattr(discovery_module, "fetch_source", fake_fetch_source)

    async with session_factory() as db:
        user = await _make_user(db)
        with pytest.raises(DiscoveryError):
            await capture_job_from_url(
                db, user_id=user.id, url="https://dead.example.com/x", settings=_fake_settings()
            )


async def test_capture_job_from_text_never_guesses_absent_fields(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The model returns only remote_type (the one required field) — every other field
    must come back None, never a fabricated guess."""
    llm = _FakeLLMProvider({"remote_type": "unknown"})
    monkeypatch.setattr(discovery_module, "get_llm_provider", lambda settings: llm)

    async with session_factory() as db:
        user = await _make_user(db)
        posting = await capture_job_from_text(
            db, user_id=user.id, raw_text="Some vague forwarded text.", settings=_fake_settings()
        )
        assert posting.title is None
        assert posting.company_name is None
        assert posting.salary_min is None
        assert posting.remote_type == "unknown"


async def test_poll_company_feed_skips_previously_seen_postings(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    postings = [
        RawPosting(
            external_id="1",
            title="Engineer A",
            location="Remote",
            url="https://acme.example.com/jobs/1",
            posted_at="2026-09-01T00:00:00Z",
            description="Job A description text.",
            raw={"id": "1"},
        ),
        RawPosting(
            external_id="2",
            title="Engineer B",
            location="Remote",
            url="https://acme.example.com/jobs/2",
            posted_at="2026-09-02T00:00:00Z",
            description="Job B description text.",
            raw={"id": "2"},
        ),
    ]

    async def fake_fetch_greenhouse(client: object, company_slug: str) -> list[RawPosting]:
        return postings

    monkeypatch.setattr(discovery_module, "fetch_greenhouse_postings", fake_fetch_greenhouse)

    async with session_factory() as db:
        user = await _make_user(db)
        feed = JobBoardFeed(user_id=user.id, board="greenhouse", company_slug="acme")
        db.add(feed)
        await db.flush()

        created = await poll_company_feed(db, feed, settings=_fake_settings())
        await db.commit()
        assert len(created) == 2
        assert feed.last_poll_error is None
        assert feed.last_polled_at is not None

        created_again = await poll_company_feed(db, feed, settings=_fake_settings())
        assert created_again == []


async def test_poll_company_feed_records_failure_on_board_error(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_fetch_greenhouse(client: object, company_slug: str) -> list[RawPosting]:
        raise BoardApiError("Greenhouse returned HTTP 404 for 'nonexistent'")

    monkeypatch.setattr(discovery_module, "fetch_greenhouse_postings", fake_fetch_greenhouse)

    async with session_factory() as db:
        user = await _make_user(db)
        feed = JobBoardFeed(user_id=user.id, board="greenhouse", company_slug="nonexistent")
        db.add(feed)
        await db.flush()

        with pytest.raises(DiscoveryError):
            await poll_company_feed(db, feed, settings=_fake_settings())
        await db.commit()

        assert feed.last_poll_error is not None


async def test_poll_company_feed_dedupes_by_description_hash_across_channels(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A posting syndicated under a different external id (e.g. re-posted on another
    board) must not be double-counted once its description content matches an existing
    posting for this user."""
    shared_description = "Identical job description text used to test cross-posting dedup."

    async def fake_fetch_greenhouse(client: object, company_slug: str) -> list[RawPosting]:
        return [
            RawPosting(
                external_id="dup-1",
                title="Engineer",
                location="Remote",
                url=None,
                posted_at=None,
                description=shared_description,
                raw={},
            )
        ]

    monkeypatch.setattr(discovery_module, "fetch_greenhouse_postings", fake_fetch_greenhouse)

    async with session_factory() as db:
        user = await _make_user(db)
        existing = JobPosting(
            user_id=user.id,
            source_channel="manual_paste",
            description_text=shared_description,
            description_hash=discovery_module.content_hash(shared_description),
            remote_type="unknown",
        )
        db.add(existing)
        feed = JobBoardFeed(user_id=user.id, board="greenhouse", company_slug="acme")
        db.add(feed)
        await db.flush()

        created = await poll_company_feed(db, feed, settings=_fake_settings())
        assert created == []


async def test_poll_company_feed_requires_usajobs_api_key(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as db:
        user = await _make_user(db)
        feed = JobBoardFeed(user_id=user.id, board="usajobs", keyword="data scientist")
        db.add(feed)
        await db.flush()

        with pytest.raises(DiscoveryError):
            await poll_company_feed(db, feed, settings=_fake_settings())
