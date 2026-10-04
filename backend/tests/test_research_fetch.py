"""app.research.fetch: the happy path that the SSRF/size tests in test_redteam_ssrf.py don't
cover — a real HTML page becomes extracted article text. Also pins that trafilatura runs in a
worker thread, not on the event loop, so a long page can't stall every other request on a
single-worker deployment."""

import asyncio

import httpx
import pytest
import trafilatura

from app.research import fetch

ARTICLE = (
    "<html><head><title>Acme ML role</title></head><body><article>"
    + "".join(
        f"<p>Paragraph {i}: the Senior Machine Learning Engineer role at Acme requires five years "
        f"of hands-on PyTorch work, computer vision experience, and comfort shipping models to "
        f"production on a small team that moves quickly.</p>"
        for i in range(8)
    )
    + "</article></body></html>"
)

_RealAsyncClient = httpx.AsyncClient


@pytest.fixture(autouse=True)
def _no_real_robots_txt_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fetch, "_check_robots", lambda url: True)


def _client_factory(handler):  # type: ignore[no-untyped-def]
    def factory(**kwargs: object) -> httpx.AsyncClient:
        return _RealAsyncClient(transport=httpx.MockTransport(handler), **kwargs)

    return factory


async def test_an_html_page_is_extracted_to_article_text(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, text=ARTICLE)

    monkeypatch.setattr(fetch.httpx, "AsyncClient", _client_factory(handler))

    result = await fetch.fetch_source("http://8.8.8.8/article", timeout_seconds=5.0, max_chars=5000)

    assert result.fetch_error is None
    assert result.content is not None
    assert "Senior Machine Learning Engineer" in result.content


async def test_extraction_runs_in_a_worker_thread_not_on_the_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, text=ARTICLE)

    offloaded: list[object] = []
    real_to_thread = asyncio.to_thread

    async def _recording_to_thread(func, /, *args, **kwargs):  # type: ignore[no-untyped-def]
        offloaded.append(func)
        return await real_to_thread(func, *args, **kwargs)

    monkeypatch.setattr(fetch.httpx, "AsyncClient", _client_factory(handler))
    monkeypatch.setattr(fetch.asyncio, "to_thread", _recording_to_thread)

    await fetch.fetch_source("http://8.8.8.8/article", timeout_seconds=5.0, max_chars=5000)

    assert trafilatura.extract in offloaded
