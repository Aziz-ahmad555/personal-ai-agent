"""Search step: turns a query into a ranked list of candidate URLs. Kept behind a small
Protocol so the vendor (currently Tavily) can change without touching the rest of the
pipeline, and so tests can substitute a fake provider instead of hitting the network."""

from dataclasses import dataclass
from typing import Protocol

from tavily import AsyncTavilyClient

from app.config import get_settings
from app.logging import get_logger

logger = get_logger(__name__)


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
        try:
            response = await self._client.search(
                query=query, max_results=max_results, search_depth="advanced"
            )
        except Exception as exc:  # tavily-python raises its own exception hierarchy
            logger.warning("tavily_search_failed", query=query, error=str(exc))
            raise SearchError(f"Tavily search failed: {exc}") from exc

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
