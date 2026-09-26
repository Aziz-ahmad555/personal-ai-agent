import types

import httpx
import pytest
from tavily.errors import TimeoutError as TavilyTimeoutError
from tavily.errors import UsageLimitExceededError

from app.research import search


def test_get_search_provider_fails_closed_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(search, "get_settings", lambda: types.SimpleNamespace(tavily_api_key=None))

    with pytest.raises(search.SearchError):
        search.get_search_provider()


def test_get_search_provider_returns_provider_when_key_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        search, "get_settings", lambda: types.SimpleNamespace(tavily_api_key="fake-key")
    )

    provider = search.get_search_provider()
    assert isinstance(provider, search.TavilySearchProvider)


def _http_status_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://api.tavily.com/search")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError("server error", request=request, response=response)


class _FakeTavilyClient:
    def __init__(self, effects: list[Exception | dict]) -> None:
        self._effects = list(effects)
        self.call_count = 0

    async def search(self, **kwargs: object) -> dict:
        self.call_count += 1
        effect = self._effects.pop(0)
        if isinstance(effect, Exception):
            raise effect
        return effect


async def test_search_retries_a_transient_5xx_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(search, "_RETRY_BASE_DELAY_SECONDS", 0.001)
    provider = search.TavilySearchProvider(api_key="fake")
    fake = _FakeTavilyClient(
        [_http_status_error(503), _http_status_error(502), {"results": [{"url": "https://x"}]}]
    )
    provider._client = fake  # type: ignore[assignment]

    results = await provider.search("query", max_results=5)

    assert [r.url for r in results] == ["https://x"]
    assert fake.call_count == 3


async def test_search_gives_up_after_max_attempts_of_a_persistent_5xx(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(search, "_RETRY_BASE_DELAY_SECONDS", 0.001)
    provider = search.TavilySearchProvider(api_key="fake")
    fake = _FakeTavilyClient([_http_status_error(503) for _ in range(search._MAX_RETRY_ATTEMPTS)])
    provider._client = fake  # type: ignore[assignment]

    with pytest.raises(search.SearchError):
        await provider.search("query", max_results=5)

    assert fake.call_count == search._MAX_RETRY_ATTEMPTS


async def test_search_retries_a_client_side_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(search, "_RETRY_BASE_DELAY_SECONDS", 0.001)
    provider = search.TavilySearchProvider(api_key="fake")
    fake = _FakeTavilyClient([TavilyTimeoutError(30), {"results": [{"url": "https://x"}]}])
    provider._client = fake  # type: ignore[assignment]

    results = await provider.search("query", max_results=5)

    assert [r.url for r in results] == ["https://x"]
    assert fake.call_count == 2


async def test_search_does_not_retry_usage_limit_exceeded(monkeypatch: pytest.MonkeyPatch) -> None:
    """UsageLimitExceededError is Tavily's account-level quota cap, not a per-minute rate
    limit — waiting won't fix it, so it must fail on the first attempt (see the comment on
    _TRANSIENT_HTTP_STATUS_CODES for why this differs from how Gemini/Groq treat a 429)."""
    monkeypatch.setattr(search, "_RETRY_BASE_DELAY_SECONDS", 0.001)
    provider = search.TavilySearchProvider(api_key="fake")
    fake = _FakeTavilyClient([UsageLimitExceededError("quota exhausted")])
    provider._client = fake  # type: ignore[assignment]

    with pytest.raises(search.SearchError):
        await provider.search("query", max_results=5)

    assert fake.call_count == 1
