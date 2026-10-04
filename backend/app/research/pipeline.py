"""The Research Engine pipeline, wired as a LangGraph graph: search -> collect -> dedupe ->
extract -> report. Each node is a plain async function with a single deterministic-or-LLM
responsibility (documented on the node itself); state flows through a TypedDict so every
stage's input/output is inspectable rather than hidden inside one opaque agent loop.

Tier classification and source verification happen inside `collect` (they're per-source,
synchronous judgments made the moment a source is fetched); cross-checking and confidence
scoring happen inside `extract` (scoring needs the citation-verification result extraction
just produced). Both stay separately unit-testable via their own pure functions in
tiers.py / verify.py / scoring.py — the pipeline module only wires them together.

If any node sets state["error"], every later node short-circuits (returns immediately)
rather than raising, so the graph always completes and the wrapper function below reads
that single field to decide the query's final status.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.logging import get_logger
from app.research.dedupe import content_hash, find_semantic_duplicates, normalize_url
from app.research.embeddings import embed_and_store_batch
from app.research.extraction import SourceExcerpt, extract_claims
from app.research.fetch import FetchResult, fetch_source
from app.research.llm import LLMError, LLMProvider, get_llm_provider
from app.research.models import (
    ResearchClaim,
    ResearchClaimCitation,
    ResearchQuery,
    ResearchQuerySource,
    ResearchReport,
    ResearchSource,
)
from app.research.report import ClaimForReport, draft_report
from app.research.search import SearchError, SearchProvider, SearchResult, get_search_provider
from app.research.tiers import TIER_RANK, classify_domain
from app.research.verify import verify_citation_excerpt, verify_source

logger = get_logger(__name__)

SOURCE_FRESHNESS = timedelta(hours=24)

# A whole research run is capped here so a slow or hung step can't leave a query at "running"
# indefinitely. A run still "running" past the cap plus a grace period is reported as failed
# on read — that's what catches a run whose background task died with its server process,
# where this in-process cap never fires at all.
QUERY_TIMEOUT = timedelta(minutes=5)
STALL_GRACE = timedelta(minutes=1)
TIMEOUT_MESSAGE = "This research took too long and was stopped. Please try again."
STALLED_MESSAGE = "This research stopped responding before it finished. Please try again."


class PipelineState(TypedDict, total=False):
    query_id: str
    query_text: str
    purpose: str | None
    error: str | None
    search_results: list[dict[str, Any]]
    collected_source_ids: list[str]
    deduped_source_ids: list[str]
    claim_ids: list[str]
    extraction_uncertainties: list[str]


def _domain_of(url: str) -> str:
    from urllib.parse import urlparse

    return urlparse(url).netloc.lower().removeprefix("www.")


def _as_utc(value: datetime) -> datetime:
    """Rows are always written with an explicit UTC datetime, but SQLite (used in tests;
    Postgres in production preserves tzinfo correctly) drops the tzinfo on round-trip —
    without this, comparing a value just read back from SQLite against datetime.now(UTC)
    raises TypeError instead of just being wrong on the one backend that needs it."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def build_pipeline(
    *,
    db: AsyncSession,
    settings: Settings,
    search_provider: SearchProvider,
    llm_provider: LLMProvider,
) -> Any:
    async def search_node(state: PipelineState) -> dict[str, Any]:
        if state.get("error"):
            return {}
        try:
            results = await search_provider.search(
                state["query_text"], max_results=settings.research_max_sources_per_query
            )
        except SearchError as exc:
            return {"error": str(exc)}
        return {
            "search_results": [
                {"url": r.url, "title": r.title, "snippet": r.snippet, "rank": r.rank}
                for r in results
            ]
        }

    async def collect_node(state: PipelineState) -> dict[str, Any]:
        if state.get("error"):
            return {}
        query_uuid = uuid.UUID(state["query_id"])
        search_results = state.get("search_results", [])
        now = datetime.now(UTC)

        # Phase A: which candidates already have a fresh, previously-fetched source row?
        plan: list[tuple[dict[str, Any], str, ResearchSource | None, bool]] = []
        for result in search_results:
            normalized = normalize_url(result["url"])
            existing = (
                await db.execute(
                    select(ResearchSource).where(ResearchSource.normalized_url == normalized)
                )
            ).scalar_one_or_none()
            fresh = (
                existing is not None
                and existing.fetched_at is not None
                and (now - _as_utc(existing.fetched_at)) < SOURCE_FRESHNESS
            )
            plan.append((result, normalized, existing, fresh))

        # Phase B: fetch anything not fresh, concurrently (network only — no DB access here,
        # since AsyncSession is not safe to use from multiple coroutines at once).
        semaphore = asyncio.Semaphore(settings.research_fetch_concurrency)

        async def _bounded_fetch(url: str) -> FetchResult:
            async with semaphore:
                return await fetch_source(
                    url,
                    timeout_seconds=settings.research_fetch_timeout_seconds,
                    max_chars=settings.research_max_content_chars,
                )

        to_fetch = [i for i, (_, _, _, fresh) in enumerate(plan) if not fresh]
        fetched = await asyncio.gather(*[_bounded_fetch(plan[i][0]["url"]) for i in to_fetch])
        fetch_by_index = dict(zip(to_fetch, fetched, strict=True))

        # Phase C: sequential DB writes.
        linked_source_ids: list[str] = []
        for i, (result, normalized, existing, fresh) in enumerate(plan):
            if fresh and existing is not None:
                source = existing
            else:
                fr = fetch_by_index[i]
                passed, reason = verify_source(
                    http_status=fr.http_status, content=fr.content, fetch_error=fr.fetch_error
                )
                domain = _domain_of(fr.final_url)
                tier, tier_rationale = classify_domain(domain)

                source = existing or ResearchSource(
                    normalized_url=normalized,
                    original_url=result["url"],
                    domain=domain,
                    tier_rationale="",
                )
                if existing is None:
                    db.add(source)

                source.domain = domain
                source.title = fr.title
                source.tier = tier
                source.tier_rationale = tier_rationale
                source.content = fr.content
                source.content_hash = content_hash(fr.content) if fr.content else None
                source.http_status = fr.http_status
                source.fetch_error = None if passed else reason
                source.fetched_at = now
                source.published_at = fr.published_at
                await db.flush()

            if str(source.id) not in linked_source_ids:
                existing_link = (
                    await db.execute(
                        select(ResearchQuerySource).where(
                            ResearchQuerySource.query_id == query_uuid,
                            ResearchQuerySource.source_id == source.id,
                        )
                    )
                ).scalar_one_or_none()
                if existing_link is None:
                    db.add(
                        ResearchQuerySource(
                            query_id=query_uuid,
                            source_id=source.id,
                            search_rank=result["rank"],
                            search_snippet=result["snippet"],
                        )
                    )
                linked_source_ids.append(str(source.id))

        await db.flush()
        return {"collected_source_ids": linked_source_ids}

    async def dedupe_node(state: PipelineState) -> dict[str, Any]:
        if state.get("error"):
            return {}
        query_uuid = uuid.UUID(state["query_id"])
        source_ids = [uuid.UUID(s) for s in state.get("collected_source_ids", [])]
        if not source_ids:
            return {"deduped_source_ids": []}

        sources = (
            (await db.execute(select(ResearchSource).where(ResearchSource.id.in_(source_ids))))
            .scalars()
            .all()
        )
        verified = [s for s in sources if s.is_verified]

        # Exact dedup by content hash.
        canonical_by_hash: dict[str, ResearchSource] = {}
        duplicate_of: dict[str, str] = {}
        for s in verified:
            if s.content_hash is None:
                continue
            if s.content_hash in canonical_by_hash:
                duplicate_of[str(s.id)] = str(canonical_by_hash[s.content_hash].id)
            else:
                canonical_by_hash[s.content_hash] = s

        # Semantic dedup (Voyage embeddings) among what's left.
        remaining = [s for s in verified if str(s.id) not in duplicate_of]
        vectors_by_source = await embed_and_store_batch(
            db,
            query_id=query_uuid,
            owner_type="source_chunk",
            items=[(s.id, s.content or "") for s in remaining],
        )
        embeddings: dict[str, list[float]] = {
            str(source_id): vectors[0] for source_id, vectors in vectors_by_source.items()
        }
        if embeddings:
            duplicate_of.update(find_semantic_duplicates(embeddings))

        if duplicate_of:
            query_sources = (
                (
                    await db.execute(
                        select(ResearchQuerySource).where(
                            ResearchQuerySource.query_id == query_uuid
                        )
                    )
                )
                .scalars()
                .all()
            )
            qs_by_source = {str(qs.source_id): qs for qs in query_sources}
            for dup_id, canonical_id in duplicate_of.items():
                qs = qs_by_source.get(dup_id)
                if qs is not None:
                    qs.is_duplicate_of_source_id = uuid.UUID(canonical_id)
            await db.flush()

        deduped_ids = [str(s.id) for s in verified if str(s.id) not in duplicate_of]
        return {"deduped_source_ids": deduped_ids}

    async def extract_node(state: PipelineState) -> dict[str, Any]:
        if state.get("error"):
            return {}

        from app.research.scoring import score_claim

        query_uuid = uuid.UUID(state["query_id"])
        deduped_ids = [uuid.UUID(s) for s in state.get("deduped_source_ids", [])]
        sources = (
            (await db.execute(select(ResearchSource).where(ResearchSource.id.in_(deduped_ids))))
            .scalars()
            .all()
        )

        short_id_map = {f"s{i + 1}": s for i, s in enumerate(sources)}
        excerpts = [
            SourceExcerpt(
                id=sid, domain=s.domain, tier=s.tier, title=s.title, content=s.content or ""
            )
            for sid, s in short_id_map.items()
        ]

        try:
            result = await extract_claims(
                llm_provider,
                query_text=state["query_text"],
                purpose=state.get("purpose"),
                sources=excerpts,
            )
        except LLMError as exc:
            return {"error": str(exc)}

        claim_ids: list[str] = []
        claim_texts: list[tuple[uuid.UUID, str]] = []
        for extracted in result.claims:
            resolved = [
                (
                    cit,
                    short_id_map[cit.source_id],
                    verify_citation_excerpt(cit.excerpt, short_id_map[cit.source_id].content or ""),
                )
                for cit in extracted.citations
                if cit.source_id in short_id_map
            ]
            if not resolved:
                continue  # cites no known source — cannot be trusted at all, drop entirely

            all_verified = all(verified for _, _, verified in resolved)
            supporting_domains: set[str] = set()
            best_tier = "unknown"
            newest_age_days: float | None = None
            has_contradiction = any(cit.stance == "contradicts" for cit, _, _ in resolved)

            for cit, source, verified in resolved:
                if cit.stance != "supports" or not verified:
                    continue
                supporting_domains.add(source.domain)
                if TIER_RANK.get(source.tier, 0) > TIER_RANK.get(best_tier, 0):
                    best_tier = source.tier
                if source.fetched_at is not None:
                    age = (datetime.now(UTC) - _as_utc(source.fetched_at)).total_seconds() / 86400
                    if newest_age_days is None or age < newest_age_days:
                        newest_age_days = age

            scored = score_claim(
                best_tier=best_tier,
                independent_corroborations=len(supporting_domains),
                all_citations_verified=all_verified,
                has_contradiction=has_contradiction,
                newest_source_age_days=newest_age_days,
            )

            claim = ResearchClaim(
                query_id=query_uuid,
                claim_text=extracted.claim_text,
                claim_type=extracted.claim_type,
                value=extracted.value,
                status=scored.status,
                confidence_score=scored.confidence_score,
                confidence_rationale=scored.rationale,
            )
            db.add(claim)
            await db.flush()

            for cit, source, verified in resolved:
                db.add(
                    ResearchClaimCitation(
                        claim_id=claim.id,
                        source_id=source.id,
                        excerpt=cit.excerpt,
                        stance=cit.stance,
                        excerpt_verified=verified,
                    )
                )

            claim_texts.append((claim.id, extracted.claim_text))
            claim_ids.append(str(claim.id))

        await embed_and_store_batch(db, query_id=query_uuid, owner_type="claim", items=claim_texts)
        await db.flush()
        return {"claim_ids": claim_ids, "extraction_uncertainties": result.uncertainties}

    async def report_node(state: PipelineState) -> dict[str, Any]:
        if state.get("error"):
            return {}

        query_uuid = uuid.UUID(state["query_id"])
        claim_uuids = [uuid.UUID(c) for c in state.get("claim_ids", [])]
        claims = (
            (
                await db.execute(
                    select(ResearchClaim)
                    .where(ResearchClaim.id.in_(claim_uuids))
                    .order_by(ResearchClaim.confidence_score.desc())
                )
            )
            .scalars()
            .all()
            if claim_uuids
            else []
        )

        short_id_map = {f"c{i + 1}": c for i, c in enumerate(claims)}
        claims_for_report = [
            ClaimForReport(
                id=sid,
                claim_text=c.claim_text,
                status=c.status,
                confidence_score=c.confidence_score,
            )
            for sid, c in short_id_map.items()
        ]

        try:
            draft = await draft_report(
                llm_provider,
                query_text=state["query_text"],
                purpose=state.get("purpose"),
                claims=claims_for_report,
            )
        except LLMError as exc:
            return {"error": str(exc)}

        referenced_real_ids = [
            str(short_id_map[sid].id) for sid in draft.referenced_claim_ids if sid in short_id_map
        ]
        seen: set[str] = set()
        uncertainties: list[str] = []
        for u in [*state.get("extraction_uncertainties", []), *draft.uncertainties]:
            if u not in seen:
                seen.add(u)
                uncertainties.append(u)

        db.add(
            ResearchReport(
                query_id=query_uuid,
                summary=draft.summary,
                uncertainties=uncertainties,
                claim_ids=referenced_real_ids,
                model_used=(
                    settings.gemini_model
                    if settings.llm_provider == "gemini"
                    else settings.anthropic_model
                ),
            )
        )
        await db.flush()
        return {}

    graph = StateGraph(PipelineState)
    graph.add_node("search", search_node)
    graph.add_node("collect", collect_node)
    graph.add_node("dedupe", dedupe_node)
    graph.add_node("extract", extract_node)
    graph.add_node("report", report_node)
    graph.add_edge(START, "search")
    graph.add_edge("search", "collect")
    graph.add_edge("collect", "dedupe")
    graph.add_edge("dedupe", "extract")
    graph.add_edge("extract", "report")
    graph.add_edge("report", END)
    return graph.compile()


def is_stalled(query: ResearchQuery, *, now: datetime | None = None) -> bool:
    if query.status not in ("pending", "running"):
        return False
    return (now or datetime.now(UTC)) - _as_utc(query.created_at) > QUERY_TIMEOUT + STALL_GRACE


async def run_research_query(db: AsyncSession, query_id: uuid.UUID) -> None:
    """Entry point for the background task. Owns the full lifecycle: marks the query
    running, executes the pipeline, and always leaves it in a terminal completed/failed
    state with a human-readable error rather than leaving it stuck at "running"."""
    query = await db.get(ResearchQuery, query_id)
    if query is None:
        logger.warning("research_query_not_found", query_id=str(query_id))
        return

    query.status = "running"
    await db.commit()

    settings = get_settings()
    error: str | None = None
    try:
        search_provider = get_search_provider()
        llm_provider = get_llm_provider(settings)
        pipeline = build_pipeline(
            db=db, settings=settings, search_provider=search_provider, llm_provider=llm_provider
        )
        final_state: PipelineState = await asyncio.wait_for(
            pipeline.ainvoke(
                {
                    "query_id": str(query_id),
                    "query_text": query.query_text,
                    "purpose": query.purpose,
                    "error": None,
                }
            ),
            timeout=QUERY_TIMEOUT.total_seconds(),
        )
        error = final_state.get("error")
    except TimeoutError:
        logger.warning("research_pipeline_timed_out", query_id=str(query_id))
        await db.rollback()
        query = await db.get(ResearchQuery, query_id)
        assert query is not None
        error = TIMEOUT_MESSAGE
    except (SearchError, LLMError) as exc:
        error = str(exc)
    except Exception as exc:  # last-resort guardrail: a crash must still resolve the query
        logger.exception("research_pipeline_crashed", query_id=str(query_id))
        error = f"Unexpected error: {exc}"

    query.status = "failed" if error else "completed"
    query.error = error
    query.completed_at = datetime.now(UTC)
    await db.commit()


__all__ = ["run_research_query", "PipelineState", "build_pipeline", "SearchResult"]
