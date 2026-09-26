"""Search step: turns a query into a ranked list of candidate URLs. Kept behind a small
Protocol so the vendor (currently Tavily) can change without touching the rest of the
pipeline, and so tests can substitute a fake provider instead of hitting the network."""

import asyncio
from dataclasses import dataclass
from typing import Protocol

import httpx
from tavily import AsyncTavilyClient
from tavily.errors import TimeoutError as TavilyTimeoutError

from app.config import get_settings
from app.logging import get_logger

logger = get_logger(__name__)

# Mirrors app.research.llm's retry shape. Tavily's SDK maps a 429 to UsageLimitExceededError,
# but unlike Gemini/Groq's 429 (a short per-minute rate limit, worth waiting out) Tavily's own
# naming says this is the account's overall usage cap — waiting seconds won't fix that, so it's
# deliberately excluded from the retryable set. A genuine server-side failure (5xx, surfaced as
# a bare httpx.HTTPStatusError since the SDK has no dedicated exception for it) or a client-side
# timeout (Tavily's own TimeoutError) are retried.
_TRANSIENT_HTTP_STATUS_CODES = {500, 502, 503, 504}
_MAX_RETRY_ATTEMPTS = 4
_RETRY_BASE_DELAY_SECONDS = 2.0


@dataclass(frozen=True)
class SearchResult:
    url: str
    title: str
    snippet: str
    rank: int


class SearchError(RuntimeError):
    """Raised when the search step cannot run at all (missing key, API/network failure) —
    distinct from a successful search that legitimately returns zero results."""


class SearchProvider(Protocol):
    async def search(self, query: str, max_results: int) -> list[SearchResult]: ...


class TavilySearchProvider:
    def __init__(self, api_key: str) -> None:
        self._client = AsyncTavilyClient(api_key=api_key)

    async def search(self, query: str, max_results: int) -> list[SearchResult]:
        attempt = 0
        while True:
            attempt += 1
            try:
                response = await self._client.search(
                    query=query, max_results=max_results, search_depth="advanced"
                )
                break
            except Exception as exc:  # tavily-python raises its own exception hierarchy
                transient = isinstance(exc, TavilyTimeoutError) or (
                    isinstance(exc, httpx.HTTPStatusError)
                    and exc.response.status_code in _TRANSIENT_HTTP_STATUS_CODES
                )
                if not transient or attempt >= _MAX_RETRY_ATTEMPTS:
                    logger.warning(
                        "tavily_search_failed", query=query, attempts=attempt, error=str(exc)
                    )
                    raise SearchError(f"Tavily search failed: {exc}") from exc
                delay = _RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1))
                logger.warning(
                    "tavily_transient_error_retrying",
                    query=query,
                    attempt=attempt,
                    delay_seconds=delay,
                    error=str(exc),
                )
                await asyncio.sleep(delay)

        results = response.get("results", []) if isinstance(response, dict) else []
        return [
            SearchResult(
                url=item["url"],
                title=item.get("title") or item["url"],
                snippet=item.get("content") or "",
                rank=index,
            )
            for index, item in enumerate(results)
            if item.get("url")
        ]


def get_search_provider() -> SearchProvider:
    settings = get_settings()
    if not settings.tavily_api_key:
        raise SearchError(
            "TAVILY_API_KEY is not set — the Research Engine's search step cannot run "
            "without it. Add it to .env."
        )
    return TavilySearchProvider(settings.tavily_api_key)
