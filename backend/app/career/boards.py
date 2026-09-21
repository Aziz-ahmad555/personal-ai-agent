"""Plain HTTP clients for public, documented job-board APIs that companies deliberately
publish for third-party consumption — no scraping, no ToS violation, deterministic (no
LLM). Each function takes an httpx.AsyncClient the caller manages (mirrors
app.gmail.client), so it's testable with a duck-typed fake client and no real network.

LinkedIn and Indeed are deliberately NOT here: those need an official partner/publisher
API agreement, which is CLAUDE.md Phase 7, not this one — and neither is ever scraped,
regardless of phase.
"""

from dataclasses import dataclass

import httpx

USER_AGENT = "PersonalAIAgent-CareerBot/0.1 (single-user personal job-search assistant)"


class BoardApiError(RuntimeError):
    """A board's API call failed outright (network/HTTP error) — never means "zero jobs
    found"; the caller must record this distinctly from an empty-but-successful result."""


@dataclass(frozen=True)
class RawPosting:
    external_id: str
    title: str | None
    location: str | None
    url: str | None
    posted_at: str | None
    description: str | None
    raw: dict[str, object]


def _raise_for_status(response: httpx.Response, *, board: str, identifier: str) -> None:
    if response.status_code != 200:
        raise BoardApiError(f"{board} returned HTTP {response.status_code} for {identifier!r}")


async def fetch_greenhouse_postings(
    client: httpx.AsyncClient, company_slug: str
) -> list[RawPosting]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{company_slug}/jobs"
    try:
        response = await client.get(
            url, params={"content": "true"}, headers={"User-Agent": USER_AGENT}
        )
    except httpx.HTTPError as exc:
        raise BoardApiError(f"Greenhouse request failed: {exc}") from exc
    _raise_for_status(response, board="Greenhouse", identifier=company_slug)

    data = response.json()
    return [
        RawPosting(
            external_id=str(job["id"]),
            title=job.get("title"),
            location=(job.get("location") or {}).get("name"),
            url=job.get("absolute_url"),
            posted_at=job.get("updated_at"),
            description=job.get("content"),
            raw=job,
        )
        for job in data.get("jobs", [])
    ]


async def fetch_lever_postings(client: httpx.AsyncClient, company_slug: str) -> list[RawPosting]:
    url = f"https://api.lever.co/v0/postings/{company_slug}"
    try:
        response = await client.get(
            url, params={"mode": "json"}, headers={"User-Agent": USER_AGENT}
        )
    except httpx.HTTPError as exc:
        raise BoardApiError(f"Lever request failed: {exc}") from exc
    _raise_for_status(response, board="Lever", identifier=company_slug)

    data = response.json()
    return [
        RawPosting(
            external_id=str(job["id"]),
            title=job.get("text"),
            location=(job.get("categories") or {}).get("location"),
            url=job.get("hostedUrl"),
            posted_at=str(job["createdAt"]) if job.get("createdAt") is not None else None,
            description=job.get("descriptionPlain") or job.get("description"),
            raw=job,
        )
        for job in data
    ]


async def fetch_ashby_postings(client: httpx.AsyncClient, company_slug: str) -> list[RawPosting]:
    url = f"https://api.ashbyhq.com/posting-api/job-board/{company_slug}"
    try:
        response = await client.get(url, headers={"User-Agent": USER_AGENT})
    except httpx.HTTPError as exc:
        raise BoardApiError(f"Ashby request failed: {exc}") from exc
    _raise_for_status(response, board="Ashby", identifier=company_slug)

    data = response.json()
    return [
        RawPosting(
            external_id=str(job["id"]),
            title=job.get("title"),
            location=job.get("location"),
            url=job.get("jobUrl") or job.get("applyUrl"),
            posted_at=job.get("publishedAt"),
            description=job.get("descriptionPlain") or job.get("description"),
            raw=job,
        )
        for job in data.get("jobs", [])
    ]


async def fetch_usajobs_postings(
    client: httpx.AsyncClient, keyword: str, *, api_key: str, user_agent_email: str
) -> list[RawPosting]:
    """USAJobs' official public API (data.usajobs.gov) requires a free registered key and
    the requester's own contact email as User-Agent — both come from config (never
    hardcoded), and the key is never logged."""
    url = "https://data.usajobs.gov/api/search"
    headers = {
        "Host": "data.usajobs.gov",
        "User-Agent": user_agent_email,
        "Authorization-Key": api_key,
    }
    try:
        response = await client.get(url, params={"Keyword": keyword}, headers=headers)
    except httpx.HTTPError as exc:
        raise BoardApiError(f"USAJobs request failed: {exc}") from exc
    _raise_for_status(response, board="USAJobs", identifier=keyword)

    data = response.json()
    items = (data.get("SearchResult") or {}).get("SearchResultItems", [])
    postings = []
    for item in items:
        job = item.get("MatchedObjectDescriptor", {})
        user_area = job.get("UserArea", {}) or {}
        details = user_area.get("Details", {}) or {}
        postings.append(
            RawPosting(
                external_id=str(item.get("MatchedObjectId") or job.get("PositionID", "")),
                title=job.get("PositionTitle"),
                location=job.get("PositionLocationDisplay"),
                url=job.get("PositionURI"),
                posted_at=job.get("PublicationStartDate"),
                description=details.get("JobSummary"),
                raw=job,
            )
        )
    return postings
