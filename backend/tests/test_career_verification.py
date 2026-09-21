"""Employer verification tests with the Research Engine pipeline's own dependencies faked
(same approach as test_research_pipeline.py) — no real network, search, or LLM calls.
Covers all three verdicts, the per-employer cache, and fraud assessment folding in the
verification status."""

import re
import types
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.career.models import EmployerVerification, JobPosting
from app.career.verification import (
    EMPLOYER_VERIFICATION_FRESHNESS,
    assess_job_fraud,
    employer_key_for,
    verify_and_assess_job,
    verify_employer,
)
from app.db.models import User
from app.research import pipeline as pipeline_module
from app.research.fetch import FetchResult
from app.research.search import SearchResult

COMPANY_DOMAIN = "acmecorp.example"  # exactly 2 labels — classify_domain's employer_domains
# matching reduces to a "registrable" (last-two-label) domain on both sides (see
# app.research.tiers._registrable_domain, a best-effort heuristic, not a full public-
# suffix-list implementation), so a 3-label domain like "acme.example.com" would silently
# reduce to "example.com" and never match its own employer_domains entry.
OFFICIAL_URL = f"https://{COMPANY_DOMAIN}/about"
UNRELATED_URL = "https://some-random-blog.example/posts/acme"

OFFICIAL_EXCERPT = "Acme Corp is a real company headquartered in Springfield, founded in 2005."
OFFICIAL_CONTENT = (OFFICIAL_EXCERPT + " ") * 5

UNRELATED_EXCERPT = "Some blogger mentions Acme Corp in passing while discussing local businesses."
UNRELATED_CONTENT = (UNRELATED_EXCERPT + " ") * 5


class _FakeSearchProvider:
    def __init__(self, results: list[SearchResult]) -> None:
        self._results = results

    async def search(self, query: str, max_results: int) -> list[SearchResult]:
        return self._results


def _source_id_for(user_message: str, excerpt_marker: str) -> str:
    """The dedupe/extract steps query sources with no ORDER BY, so with more than one
    source a test can't assume which real source lands on short id "s1" vs "s2" — a real
    LLM call never has this problem (it always sees the correct label-to-content pairing
    fresh each run); only a fixed fake payload would. This reads the actual pairing out of
    the prompt the pipeline built, the same information a real model would use."""
    for block in user_message.split("---"):
        if excerpt_marker in block:
            match = re.search(r"source_id:\s*(\S+)", block)
            if match:
                return match.group(1)
    raise AssertionError(f"No source block in the prompt contained: {excerpt_marker!r}")


class _FakeLLMProvider:
    """Each entry in `payloads` is either a fixed dict, or a callable(kwargs) -> dict for
    a response that must be built from the actual prompt (see _source_id_for)."""

    def __init__(self, payloads: list[dict | Callable[[dict], dict]]) -> None:
        self._payloads = payloads
        self.calls = 0

    async def generate_structured(self, **kwargs: object) -> dict:
        entry = self._payloads[self.calls]
        self.calls += 1
        return entry(kwargs) if callable(entry) else entry


def _patch_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    *,
    search_results: list[SearchResult],
    fetch_results: dict[str, FetchResult],
    llm_payloads: list[dict | Callable[[dict], dict]],
) -> _FakeLLMProvider:
    monkeypatch.setattr(
        pipeline_module, "get_search_provider", lambda: _FakeSearchProvider(search_results)
    )

    async def _fake_fetch_source(
        url: str, *, timeout_seconds: float, max_chars: int
    ) -> FetchResult:
        return fetch_results[url]

    monkeypatch.setattr(pipeline_module, "fetch_source", _fake_fetch_source)
    llm = _FakeLLMProvider(llm_payloads)
    monkeypatch.setattr(pipeline_module, "get_llm_provider", lambda settings: llm)

    real_settings = pipeline_module.get_settings()
    fake_settings = types.SimpleNamespace(
        research_max_sources_per_query=real_settings.research_max_sources_per_query,
        research_fetch_timeout_seconds=real_settings.research_fetch_timeout_seconds,
        research_fetch_concurrency=real_settings.research_fetch_concurrency,
        research_max_content_chars=real_settings.research_max_content_chars,
        llm_provider="gemini",
        gemini_model="fake-gemini-model",
        anthropic_model="fake-anthropic-model",
    )
    monkeypatch.setattr(pipeline_module, "get_settings", lambda: fake_settings)
    return llm


@pytest.fixture(autouse=True)
def _fake_research_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _disabled(texts: list[str]) -> list[list[float]] | None:
        return None

    monkeypatch.setattr("app.research.embeddings.embed_texts", _disabled)


async def _make_user(db: AsyncSession) -> User:
    user = User(email=f"verify-test-{uuid.uuid4()}@example.com", hashed_password="x")
    db.add(user)
    await db.flush()
    return user


def _fetch_result(url: str, content: str) -> FetchResult:
    return FetchResult(
        final_url=url,
        http_status=200,
        content=content,
        title="About Acme",
        published_at=datetime(2026, 9, 1, tzinfo=UTC),
        fetch_error=None,
    )


async def test_verify_employer_returns_verified_for_official_source(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    extraction_payload = {
        "claims": [
            {
                "claim_text": "Acme Corp is a real company founded in 2005.",
                "claim_type": "employer_existence",
                "citations": [
                    {
                        "source_id": "s1",
                        "excerpt": OFFICIAL_EXCERPT,
                        "stance": "supports",
                    }
                ],
            }
        ],
        "uncertainties": [],
    }
    report_payload = {"summary": "Acme Corp appears to be a real company.", "uncertainties": []}

    _patch_pipeline(
        monkeypatch,
        search_results=[SearchResult(url=OFFICIAL_URL, title="About", snippet="...", rank=0)],
        fetch_results={OFFICIAL_URL: _fetch_result(OFFICIAL_URL, OFFICIAL_CONTENT)},
        llm_payloads=[extraction_payload, report_payload],
    )

    async with session_factory() as db:
        user = await _make_user(db)
        job = JobPosting(
            user_id=user.id, source_channel="manual_paste", company_name="Acme Corp",
            company_domain=COMPANY_DOMAIN, remote_type="unknown",
        )
        db.add(job)
        await db.flush()

        verification = await verify_employer(db, job, user_id=user.id)
        await db.commit()

        assert verification.verification_status == "verified"
        assert verification.confidence_score >= 40
        assert verification.employer_key == COMPANY_DOMAIN


async def test_verify_employer_returns_unconfirmed_without_official_source(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A source that merely mentions the company, from an unrelated domain, must not be
    enough to call the employer verified — even with a corroborated, high-confidence claim
    at the generic level, no *official* source means "unconfirmed", not "verified"."""
    extraction_payload = {
        "claims": [
            {
                "claim_text": "A blog mentions Acme Corp as a local business.",
                "citations": [
                    {
                        "source_id": "s1",
                        "excerpt": UNRELATED_EXCERPT,
                        "stance": "supports",
                    }
                ],
            }
        ],
        "uncertainties": [],
    }
    report_payload = {"summary": "Limited information found.", "uncertainties": []}

    _patch_pipeline(
        monkeypatch,
        search_results=[SearchResult(url=UNRELATED_URL, title="Blog", snippet="...", rank=0)],
        fetch_results={UNRELATED_URL: _fetch_result(UNRELATED_URL, UNRELATED_CONTENT)},
        llm_payloads=[extraction_payload, report_payload],
    )

    async with session_factory() as db:
        user = await _make_user(db)
        job = JobPosting(
            user_id=user.id, source_channel="manual_paste", company_name="Acme Corp",
            company_domain=COMPANY_DOMAIN, remote_type="unknown",
        )
        db.add(job)
        await db.flush()

        verification = await verify_employer(db, job, user_id=user.id)
        assert verification.verification_status == "unconfirmed"


async def test_verify_employer_returns_suspicious_on_contradiction(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    contradiction_excerpt = "This company has been widely reported as a scam operation."
    contradiction_content = contradiction_excerpt * 5
    contradiction_url = "https://consumer-watchdog.example/scam-alerts/acme"

    def build_extraction_payload(kwargs: dict) -> dict:
        user_message = kwargs["user_message"]
        official_id = _source_id_for(user_message, OFFICIAL_EXCERPT)
        contradiction_id = _source_id_for(user_message, contradiction_excerpt)
        return {
            "claims": [
                {
                    "claim_text": "Acme Corp's legitimacy is disputed.",
                    "citations": [
                        {
                            "source_id": official_id,
                            "excerpt": OFFICIAL_EXCERPT,
                            "stance": "supports",
                        },
                        {
                            "source_id": contradiction_id,
                            "excerpt": contradiction_excerpt,
                            "stance": "contradicts",
                        },
                    ],
                }
            ],
            "uncertainties": [],
        }

    report_payload = {"summary": "Conflicting information found.", "uncertainties": []}

    _patch_pipeline(
        monkeypatch,
        search_results=[
            SearchResult(url=OFFICIAL_URL, title="About", snippet="...", rank=0),
            SearchResult(url=contradiction_url, title="Scam alert", snippet="...", rank=1),
        ],
        fetch_results={
            OFFICIAL_URL: _fetch_result(OFFICIAL_URL, OFFICIAL_CONTENT),
            contradiction_url: _fetch_result(contradiction_url, contradiction_content),
        },
        llm_payloads=[build_extraction_payload, report_payload],
    )

    async with session_factory() as db:
        user = await _make_user(db)
        job = JobPosting(
            user_id=user.id, source_channel="manual_paste", company_name="Acme Corp",
            company_domain=COMPANY_DOMAIN, remote_type="unknown",
        )
        db.add(job)
        await db.flush()

        verification = await verify_employer(db, job, user_id=user.id)
        assert verification.verification_status == "suspicious"


async def test_verify_employer_reuses_a_fresh_cached_result(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    extraction_payload = {
        "claims": [
            {
                "claim_text": "Acme Corp is a real company.",
                "citations": [
                    {
                        "source_id": "s1",
                        "excerpt": OFFICIAL_EXCERPT,
                        "stance": "supports",
                    }
                ],
            }
        ],
        "uncertainties": [],
    }
    report_payload = {"summary": "Acme Corp appears real.", "uncertainties": []}

    llm = _patch_pipeline(
        monkeypatch,
        search_results=[SearchResult(url=OFFICIAL_URL, title="About", snippet="...", rank=0)],
        fetch_results={OFFICIAL_URL: _fetch_result(OFFICIAL_URL, OFFICIAL_CONTENT)},
        llm_payloads=[extraction_payload, report_payload],
    )

    async with session_factory() as db:
        user = await _make_user(db)
        job_a = JobPosting(
            user_id=user.id, source_channel="manual_paste", company_name="Acme Corp",
            company_domain=COMPANY_DOMAIN, remote_type="unknown",
        )
        job_b = JobPosting(
            user_id=user.id, source_channel="manual_paste", company_name="Acme Corp",
            company_domain=COMPANY_DOMAIN, remote_type="unknown",
        )
        db.add_all([job_a, job_b])
        await db.flush()

        first = await verify_employer(db, job_a, user_id=user.id)
        assert llm.calls == 2  # extraction + report

        second = await verify_employer(db, job_b, user_id=user.id)
        assert second.id == first.id
        assert llm.calls == 2  # no new pipeline run for the second posting


async def test_verify_employer_raises_without_any_company_info(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as db:
        user = await _make_user(db)
        job = JobPosting(user_id=user.id, source_channel="manual_paste", remote_type="unknown")
        db.add(job)
        await db.flush()

        with pytest.raises(ValueError):
            await verify_employer(db, job, user_id=user.id)


async def test_employer_key_for_prefers_domain_over_name() -> None:
    assert (
        employer_key_for(company_name="Acme", company_domain="Acme.example.com")
        == "acme.example.com"
    )
    assert employer_key_for(company_name="Acme", company_domain=None) == "name:acme"
    assert employer_key_for(company_name=None, company_domain=None) is None


async def test_assess_job_fraud_folds_in_unconfirmed_employer_status(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as db:
        user = await _make_user(db)
        job = JobPosting(
            user_id=user.id, source_channel="manual_paste", company_name="Acme Corp",
            description_text="A totally ordinary job description.", remote_type="unknown",
        )
        db.add(job)
        await db.flush()

        verification = EmployerVerification(
            employer_key="name:acme corp", company_name="Acme Corp",
            verification_status="unconfirmed", confidence_score=0,
            rationale="No sources found.",
        )
        db.add(verification)
        await db.flush()

        assessment = await assess_job_fraud(
            db, job, employer_verification=verification, user_id=user.id
        )
        assert "employer_unconfirmed" in [s["code"] for s in assessment.signals]
        assert assessment.employer_verification_id == verification.id


async def test_verify_and_assess_job_handles_missing_company_gracefully(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A posting with no identifiable employer at all can't be verified, but fraud
    assessment must still run — that's exactly the kind of posting fraud signals matter
    most for."""
    async with session_factory() as db:
        user = await _make_user(db)
        job = JobPosting(user_id=user.id, source_channel="manual_paste", remote_type="unknown")
        db.add(job)
        await db.flush()

        await verify_and_assess_job(db, job.id, user_id=user.id)
        await db.commit()

        from sqlalchemy import select

        from app.career.models import JobFraudAssessment

        assessment = (
            await db.execute(
                select(JobFraudAssessment).where(JobFraudAssessment.job_posting_id == job.id)
            )
        ).scalar_one_or_none()
        assert assessment is not None
        assert assessment.employer_verification_id is None


def test_freshness_window_is_thirty_days() -> None:
    assert EMPLOYER_VERIFICATION_FRESHNESS.days == 30
