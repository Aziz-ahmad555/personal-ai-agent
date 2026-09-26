"""Job discovery: deterministic fetch/dedup, LLM only for structured field extraction
(schema-forced, per app.research.llm — never free text). Two paths:

1. Manual capture (capture_job_from_url / capture_job_from_text) — the user points at a
   specific posting; always in-scope regardless of source, since the user themselves is
   the authorized channel.
2. Board polling (poll_company_feed) — plain HTTP calls to public, documented job-board
   APIs (Greenhouse/Lever/Ashby/USAJobs) that companies publish for third-party
   consumption. LinkedIn and Indeed are deliberately absent: those require an official
   partner/publisher API agreement (CLAUDE.md Phase 7), and are never scraped.

Every discovery action is Green risk (nothing is sent externally; only public data the
user pointed at or explicitly subscribed to is read) and is logged via app.audit.service
for the same "audit everything" reason the Research Engine and Gmail sync are.
"""

import uuid
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import log_action
from app.career.boards import (
    USER_AGENT,
    BoardApiError,
    fetch_ashby_postings,
    fetch_greenhouse_postings,
    fetch_lever_postings,
    fetch_usajobs_postings,
)
from app.career.extraction import ExtractedJobFields, extract_job_fields
from app.career.models import JobBoardFeed, JobPosting
from app.config import Settings, get_settings
from app.logging import get_logger
from app.research.dedupe import content_hash, normalize_url
from app.research.fetch import fetch_source
from app.research.llm import LLMError, get_llm_provider
from app.research.models import ResearchSource
from app.research.tiers import classify_domain
from app.research.verify import verify_source

logger = get_logger(__name__)


class DiscoveryError(RuntimeError):
    """Raised when a capture/poll attempt cannot produce a result at all (fetch failure,
    LLM unavailable, board API error) — the router turns this into an error response,
    never a silently empty success."""


def _domain_of(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


async def _extract_fields(raw_text: str, settings: Settings) -> ExtractedJobFields:
    try:
        llm = get_llm_provider(settings)
        return await extract_job_fields(llm, raw_text=raw_text)
    except LLMError as exc:
        raise DiscoveryError(f"Could not extract structured job fields: {exc}") from exc


async def _get_or_create_research_source(
    db: AsyncSession,
    *,
    fetched_url: str,
    content: str | None,
    title: str | None,
    tier: str,
    tier_rationale: str,
    http_status: int | None,
    fetch_error: str | None,
    published_at: datetime | None,
) -> ResearchSource:
    normalized = normalize_url(fetched_url)
    existing = (
        await db.execute(select(ResearchSource).where(ResearchSource.normalized_url == normalized))
    ).scalar_one_or_none()
    source = existing or ResearchSource(
        normalized_url=normalized, original_url=fetched_url, domain="", tier_rationale=""
    )
    if existing is None:
        db.add(source)

    source.original_url = fetched_url
    source.domain = _domain_of(fetched_url)
    source.tier = tier
    source.tier_rationale = tier_rationale
    source.title = title
    source.content = content
    source.content_hash = content_hash(content) if content else None
    source.http_status = http_status
    source.fetch_error = fetch_error
    source.fetched_at = datetime.now(UTC)
    source.published_at = published_at
    await db.flush()
    return source


async def capture_job_from_url(
    db: AsyncSession, *, user_id: uuid.UUID, url: str, settings: Settings | None = None
) -> JobPosting:
    settings = settings or get_settings()

    normalized = normalize_url(url)
    existing = (
        await db.execute(
            select(JobPosting).where(
                JobPosting.user_id == user_id, JobPosting.source_url == normalized
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    fetched = await fetch_source(
        url,
        timeout_seconds=settings.research_fetch_timeout_seconds,
        max_chars=settings.research_max_content_chars,
    )
    passed, reason = verify_source(
        http_status=fetched.http_status, content=fetched.content, fetch_error=fetched.fetch_error
    )
    if not passed:
        raise DiscoveryError(f"Could not fetch a usable job posting from this URL: {reason}")

    domain = _domain_of(fetched.final_url)
    tier, tier_rationale = classify_domain(domain)
    source = await _get_or_create_research_source(
        db,
        fetched_url=fetched.final_url,
        content=fetched.content,
        title=fetched.title,
        tier=tier,
        tier_rationale=tier_rationale,
        http_status=fetched.http_status,
        fetch_error=fetched.fetch_error,
        published_at=fetched.published_at,
    )

    fields = await _extract_fields(fetched.content or "", settings)

    posting = JobPosting(
        user_id=user_id,
        source_channel="manual_url",
        source_url=normalized,
        company_name=fields.company_name,
        company_domain=domain,
        title=fields.title or fetched.title,
        location=fields.location,
        remote_type=fields.remote_type,
        salary_min=fields.salary_min,
        salary_max=fields.salary_max,
        salary_currency=fields.salary_currency,
        description_text=fetched.content,
        description_hash=content_hash(fetched.content) if fetched.content else None,
        posted_at=fetched.published_at,
        research_source_id=source.id,
    )
    db.add(posting)
    await db.flush()

    await log_action(
        db,
        user_id=user_id,
        action="career.job.captured_from_url",
        risk_level="green",
        summary=f"Captured a job posting from {domain}.",
        evidence={"url": url, "tier": tier, "tier_rationale": tier_rationale},
        resource_type="job_posting",
        resource_id=posting.id,
        result={"job_posting_id": str(posting.id)},
    )
    return posting


async def capture_job_from_text(
    db: AsyncSession, *, user_id: uuid.UUID, raw_text: str, settings: Settings | None = None
) -> JobPosting:
    settings = settings or get_settings()
    fields = await _extract_fields(raw_text, settings)

    posting = JobPosting(
        user_id=user_id,
        source_channel="manual_paste",
        company_name=fields.company_name,
        title=fields.title,
        location=fields.location,
        remote_type=fields.remote_type,
        salary_min=fields.salary_min,
        salary_max=fields.salary_max,
        salary_currency=fields.salary_currency,
        description_text=raw_text,
        description_hash=content_hash(raw_text),
    )
    db.add(posting)
    await db.flush()

    await log_action(
        db,
        user_id=user_id,
        action="career.job.captured_from_text",
        risk_level="green",
        summary="Captured a job posting from pasted text.",
        evidence={"chars": len(raw_text)},
        resource_type="job_posting",
        resource_id=posting.id,
        result={"job_posting_id": str(posting.id)},
    )
    return posting


async def poll_company_feed(
    db: AsyncSession,
    feed: JobBoardFeed,
    *,
    settings: Settings | None = None,
    trigger: str = "manual",
) -> list[JobPosting]:
    settings = settings or get_settings()

    try:
        async with httpx.AsyncClient(timeout=15.0, headers={"User-Agent": USER_AGENT}) as client:
            if feed.board == "usajobs":
                if not settings.usajobs_api_key or not settings.usajobs_user_agent_email:
                    raise DiscoveryError(
                        "USAJOBS_API_KEY / USAJOBS_USER_AGENT_EMAIL are not configured."
                    )
                raw_postings = await fetch_usajobs_postings(
                    client,
                    feed.keyword or "",
                    api_key=settings.usajobs_api_key,
                    user_agent_email=settings.usajobs_user_agent_email,
                )
            elif feed.board in ("greenhouse", "lever", "ashby"):
                if not feed.company_slug:
                    raise DiscoveryError(f"{feed.board} feeds require a company_slug.")
                # Direct name calls (not a dict of function refs built at import time) so
                # each fetcher stays independently monkeypatchable in tests, the same way
                # app.research.pipeline patches fetch_source by module attribute.
                if feed.board == "greenhouse":
                    raw_postings = await fetch_greenhouse_postings(client, feed.company_slug)
                elif feed.board == "lever":
                    raw_postings = await fetch_lever_postings(client, feed.company_slug)
                else:
                    raw_postings = await fetch_ashby_postings(client, feed.company_slug)
            else:
                raise DiscoveryError(f"Unknown board: {feed.board}")
    except BoardApiError as exc:
        feed.last_poll_error = str(exc)
        feed.last_polled_at = datetime.now(UTC)
        await db.flush()
        await log_action(
            db,
            user_id=feed.user_id,
            action="career.feed.poll_failed",
            risk_level="green",
            summary=f"Polling the {feed.board} feed failed.",
            evidence={"feed_id": str(feed.id), "trigger": trigger},
            resource_type="job_board_feed",
            resource_id=feed.id,
            error=str(exc),
        )
        raise DiscoveryError(str(exc)) from exc

    created: list[JobPosting] = []
    for raw in raw_postings:
        existing = (
            await db.execute(
                select(JobPosting).where(
                    JobPosting.user_id == feed.user_id,
                    JobPosting.source_channel == feed.board,
                    JobPosting.external_id == raw.external_id,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            continue

        description = raw.description or raw.title or ""
        d_hash = content_hash(description) if description else None
        if d_hash is not None:
            dup_by_hash = (
                await db.execute(
                    select(JobPosting).where(
                        JobPosting.user_id == feed.user_id, JobPosting.description_hash == d_hash
                    )
                )
            ).scalar_one_or_none()
            if dup_by_hash is not None:
                continue

        posting = JobPosting(
            user_id=feed.user_id,
            source_channel=feed.board,
            external_id=raw.external_id,
            source_url=normalize_url(raw.url) if raw.url else None,
            company_name=feed.company_slug,
            title=raw.title,
            location=raw.location,
            remote_type="unknown",
            description_text=description or None,
            description_hash=d_hash,
            posted_at=_parse_iso(raw.posted_at),
            raw_payload=raw.raw,
        )
        db.add(posting)
        await db.flush()
        created.append(posting)

    feed.last_polled_at = datetime.now(UTC)
    feed.last_poll_error = None
    await db.flush()

    await log_action(
        db,
        user_id=feed.user_id,
        action="career.feed.polled",
        risk_level="green",
        summary=(
            f"Polled the {feed.board} feed "
            f"({feed.company_slug or feed.keyword}): {len(created)} new posting(s)."
        ),
        evidence={
            "feed_id": str(feed.id),
            "found": len(raw_postings),
            "new": len(created),
            "trigger": trigger,
        },
        resource_type="job_board_feed",
        resource_id=feed.id,
        result={"new_job_posting_ids": [str(p.id) for p in created]},
    )
    return created
