"""End-to-end pipeline tests with every network/LLM call faked — search, fetch, and the
LLM provider are all monkeypatched so these never hit Tavily, Gemini, or the real web.
Exercises the full search -> collect -> dedupe -> extract -> report flow through the API,
including the two guardrails that matter most: a claim whose citation doesn't verify
against the real stored source text gets forced to "unverified", and a claim citing a
source id the model was never given gets dropped entirely."""

import asyncio
import types
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.research import pipeline as pipeline_module
from app.research.fetch import FetchResult
from app.research.models import ResearchQuery
from app.research.search import SearchResult

CONTENT = (
    "Acme Corp is hiring a Senior Machine Learning Engineer. The role requires 5 years "
    "of experience with PyTorch and computer vision. The position offers a salary range "
    "of $150,000 to $190,000 per year, remote-friendly within the United States. "
) * 2

URL = "https://acme.example.com/careers/ml-engineer"


class _FakeSearchProvider:
    def __init__(self, results: list[SearchResult]) -> None:
        self._results = results

    async def search(self, query: str, max_results: int) -> list[SearchResult]:
        return self._results


class _FakeLLMProvider:
    """Returns each queued payload in order — first call is extraction, second is report."""

    def __init__(self, payloads: list[dict]) -> None:
        self._payloads = payloads
        self.calls = 0

    async def generate_structured(self, **kwargs: object) -> dict:
        payload = self._payloads[self.calls]
        self.calls += 1
        return payload


@pytest.fixture(autouse=True)
def _fake_research_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Runs the pipeline with embeddings disabled (the "no VOYAGE_API_KEY" fail-closed
    path): semantic dedup is simply skipped, exact-hash dedup still runs. The Voyage
    wrapper is imported directly into app.research.embeddings, so it needs its own patch
    target distinct from app.profile.embeddings' autouse fake in conftest.py."""

    async def _disabled(texts: list[str]) -> list[list[float]] | None:
        return None

    monkeypatch.setattr("app.research.embeddings.embed_texts", _disabled)


def _patch_pipeline_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    *,
    search_results: list[SearchResult],
    fetch_results: dict[str, FetchResult],
    llm_payloads: list[dict],
) -> None:
    monkeypatch.setattr(
        pipeline_module, "get_search_provider", lambda: _FakeSearchProvider(search_results)
    )

    async def _fake_fetch_source(
        url: str, *, timeout_seconds: float, max_chars: int
    ) -> FetchResult:
        return fetch_results[url]

    monkeypatch.setattr(pipeline_module, "fetch_source", _fake_fetch_source)
    monkeypatch.setattr(
        pipeline_module, "get_llm_provider", lambda settings: _FakeLLMProvider(llm_payloads)
    )

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


async def test_research_query_end_to_end_produces_scored_claims_and_report(
    client: AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    search_results = [
        SearchResult(url=URL, title="ML Engineer at Acme", snippet="Hiring...", rank=0)
    ]
    fetch_results = {
        URL: FetchResult(
            final_url=URL,
            http_status=200,
            content=CONTENT,
            title="ML Engineer at Acme",
            published_at=datetime(2026, 9, 1, tzinfo=UTC),
            fetch_error=None,
        )
    }

    extraction_payload = {
        "claims": [
            {
                "claim_text": "The role requires 5 years of PyTorch experience.",
                "claim_type": "requirement",
                "citations": [
                    {
                        "source_id": "s1",
                        "excerpt": "5 years of experience with PyTorch and computer vision",
                        "stance": "supports",
                    }
                ],
            },
            {
                # This citation's excerpt does not appear in the source content at all —
                # the pipeline must still create the claim but mark it unverified/score 0,
                # never trust the model's own framing of it as "supports".
                "claim_text": "The role requires 10 years of Kubernetes experience.",
                "claim_type": "requirement",
                "citations": [
                    {
                        "source_id": "s1",
                        "excerpt": "10 years of Kubernetes experience",
                        "stance": "supports",
                    }
                ],
            },
            {
                # Cites a source id that was never given to the model — must be dropped
                # entirely, not persisted as an unverified claim.
                "claim_text": "The company was founded in 1999.",
                "citations": [
                    {"source_id": "s99", "excerpt": "founded in 1999", "stance": "supports"}
                ],
            },
        ],
        "uncertainties": ["Whether visa sponsorship is offered was not stated."],
    }
    report_payload = {
        "summary": (
            "The role requires 5 years of PyTorch experience [c1]. Unverifiable claim [c99]."
        ),
        "uncertainties": [],
    }

    _patch_pipeline_dependencies(
        monkeypatch,
        search_results=search_results,
        fetch_results=fetch_results,
        llm_payloads=[extraction_payload, report_payload],
    )

    create = await client.post(
        "/research/queries",
        headers=auth_headers,
        json={
            "query_text": "What skills does Acme's ML Engineer role require?",
            "purpose": "job application prep",
        },
    )
    assert create.status_code == 201
    query_id = create.json()["id"]

    detail = await client.get(f"/research/queries/{query_id}", headers=auth_headers)
    body = detail.json()

    assert body["status"] == "completed"
    assert body["error"] is None

    assert len(body["sources"]) == 1
    assert body["sources"][0]["tier"] == "unknown"  # acme.example.com isn't in any curated tier

    # The claim citing an unknown source id was dropped entirely.
    assert len(body["claims"]) == 2

    good_claim = next(c for c in body["claims"] if "PyTorch" in c["claim_text"])
    assert good_claim["status"] == "single_source"
    assert good_claim["confidence_score"] > 0
    assert good_claim["citations"][0]["excerpt_verified"] is True

    bad_claim = next(c for c in body["claims"] if "Kubernetes" in c["claim_text"])
    assert bad_claim["status"] == "unverified"
    assert bad_claim["confidence_score"] == 0
    assert bad_claim["citations"][0]["excerpt_verified"] is False

    assert body["report"] is not None
    # The whole sentence citing the unknown [c99] marker is dropped, not just the bracket —
    # otherwise "Unverifiable claim [c99]." would survive as "Unverifiable claim.", an
    # unattributed assertion with its only citation stripped away. A real marker for an
    # actual claim survives untouched.
    assert "[c99]" not in body["report"]["summary"]
    assert "Unverifiable claim" not in body["report"]["summary"]
    assert "PyTorch" in body["report"]["summary"]
    assert good_claim["id"] in body["report"]["claim_ids"]


async def test_query_fails_cleanly_when_no_sources_verify(
    client: AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A search that only turns up a dead link must not crash — the query completes with
    zero claims and an explicit uncertainty, never a fabricated answer."""
    search_results = [SearchResult(url=URL, title="Dead link", snippet="...", rank=0)]
    fetch_results = {
        URL: FetchResult(
            final_url=URL,
            http_status=404,
            content=None,
            title=None,
            published_at=None,
            fetch_error="http_404",
        )
    }
    report_payload = {
        "summary": "No verified claims were found for this query.",
        "uncertainties": [],
    }

    # extract_claims short-circuits when there are no verified sources, so only the report
    # call reaches the (fake) LLM provider.
    _patch_pipeline_dependencies(
        monkeypatch,
        search_results=search_results,
        fetch_results=fetch_results,
        llm_payloads=[report_payload],
    )

    create = await client.post(
        "/research/queries", headers=auth_headers, json={"query_text": "Anything about a dead page"}
    )
    query_id = create.json()["id"]

    detail = await client.get(f"/research/queries/{query_id}", headers=auth_headers)
    body = detail.json()

    assert body["status"] == "completed"
    assert body["claims"] == []
    assert body["sources"][0]["fetch_error"] == "http_404"
    assert body["report"]["summary"] == "No verified claims were found for this query."


class _SlowSearchProvider:
    async def search(self, query: str, max_results: int) -> list[SearchResult]:
        await asyncio.sleep(2)
        return []


async def test_a_run_past_the_time_cap_fails_with_a_clear_retry_message(
    client: AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pipeline_module, "QUERY_TIMEOUT", timedelta(milliseconds=100))
    monkeypatch.setattr(pipeline_module, "get_search_provider", lambda: _SlowSearchProvider())

    create = await client.post(
        "/research/queries", headers=auth_headers, json={"query_text": "Slow question"}
    )
    query_id = create.json()["id"]

    body = (await client.get(f"/research/queries/{query_id}", headers=auth_headers)).json()

    assert body["status"] == "failed"
    assert body["error"] == pipeline_module.TIMEOUT_MESSAGE


async def test_a_run_still_running_long_after_the_cap_reads_as_failed(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The in-process cap never fires if the server died mid-run, so the row is left at
    "running" forever — the read path has to report it as failed instead."""
    me = (await client.get("/auth/me", headers=auth_headers)).json()
    long_ago = datetime.now(UTC) - pipeline_module.QUERY_TIMEOUT - timedelta(minutes=10)
    async with session_factory() as db:
        query = ResearchQuery(
            user_id=uuid.UUID(me["id"]),
            query_text="Orphaned question",
            status="running",
            created_at=long_ago,
        )
        db.add(query)
        await db.commit()
        query_id = str(query.id)

    detail = (await client.get(f"/research/queries/{query_id}", headers=auth_headers)).json()
    listed = (await client.get("/research/queries", headers=auth_headers)).json()

    assert detail["status"] == "failed"
    assert detail["error"] == pipeline_module.STALLED_MESSAGE
    assert listed[0]["status"] == "failed"


async def test_a_recently_started_running_query_is_not_reported_as_stalled(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    me = (await client.get("/auth/me", headers=auth_headers)).json()
    async with session_factory() as db:
        query = ResearchQuery(
            user_id=uuid.UUID(me["id"]), query_text="Fresh question", status="running"
        )
        db.add(query)
        await db.commit()
        query_id = str(query.id)

    detail = (await client.get(f"/research/queries/{query_id}", headers=auth_headers)).json()

    assert detail["status"] == "running"
    assert detail["error"] is None


async def test_a_research_run_makes_one_voyage_request_for_sources_and_one_for_claims(
    client: AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression guard for the free Voyage tier's 3-requests-per-minute limit: per-source and
    per-claim embedding calls made a single run take several minutes of rate-limit waiting."""
    url_two = "https://acme.example.com/careers/platform-engineer"
    content_two = CONTENT.replace("machine learning", "platform") + " Kubernetes is preferred."
    search_results = [
        SearchResult(url=URL, title="ML Engineer at Acme", snippet="a", rank=0),
        SearchResult(url=url_two, title="Platform Engineer at Acme", snippet="b", rank=1),
    ]
    fetch_results = {
        URL: FetchResult(
            final_url=URL,
            http_status=200,
            content=CONTENT,
            title="ML Engineer",
            published_at=datetime(2026, 9, 1, tzinfo=UTC),
            fetch_error=None,
        ),
        url_two: FetchResult(
            final_url=url_two,
            http_status=200,
            content=content_two,
            title="Platform Engineer",
            published_at=datetime(2026, 9, 1, tzinfo=UTC),
            fetch_error=None,
        ),
    }
    extraction_payload = {
        "claims": [
            {
                "claim_text": "The ML role requires 5 years of PyTorch experience.",
                "claim_type": "requirement",
                "citations": [
                    {
                        "source_id": "s1",
                        "excerpt": "5 years of experience with PyTorch and computer vision",
                        "stance": "supports",
                    }
                ],
            },
            {
                "claim_text": "The platform role prefers Kubernetes experience.",
                "claim_type": "requirement",
                "citations": [
                    {
                        "source_id": "s2",
                        "excerpt": "Kubernetes is preferred.",
                        "stance": "supports",
                    }
                ],
            },
        ],
        "uncertainties": [],
    }
    report_payload = {"summary": "Two roles.", "uncertainties": []}
    _patch_pipeline_dependencies(
        monkeypatch,
        search_results=search_results,
        fetch_results=fetch_results,
        llm_payloads=[extraction_payload, report_payload],
    )

    voyage_requests: list[int] = []
    vectors_seen: list[list[float]] = []

    async def _recording_embed_texts(texts: list[str], *, input_type: str = "document") -> list:
        voyage_requests.append(len(texts))
        # Orthogonal vectors: parallel fakes would make semantic dedup drop one of the sources.
        vectors = []
        for _ in texts:
            vector = [0.0] * 512
            vector[len(vectors_seen)] = 1.0
            vectors_seen.append(vector)
            vectors.append(vector)
        return vectors

    monkeypatch.setattr("app.research.embeddings.embed_texts", _recording_embed_texts)

    create = await client.post(
        "/research/queries", headers=auth_headers, json={"query_text": "Two roles at Acme"}
    )
    body = (
        await client.get(f"/research/queries/{create.json()['id']}", headers=auth_headers)
    ).json()

    assert body["status"] == "completed"
    assert voyage_requests == [2, 2]
