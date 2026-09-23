"""Red-team Track A, item 3: SSRF. app.research.fetch is the one place in the app that fetches
an arbitrary external URL — both a job posting captured by URL (app.career.discovery) and the
Research Engine's web sources (app.research.pipeline) go through it. Real gap found and fixed
in this pass: nothing validated the target address, so a URL (or a redirect to one) pointing at
localhost, an RFC1918 address, or the cloud metadata endpoint (169.254.169.254) would have been
fetched exactly like any public page.

IP-literal URLs are used throughout so these tests never touch the network or DNS — resolving a
literal IP is a local operation, not a lookup.
"""

import httpx
import pytest

from app.research import fetch


@pytest.fixture(autouse=True)
def _no_real_robots_txt_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    """_check_robots uses urllib, not httpx — unaffected by the httpx.AsyncClient patches
    below, and would otherwise make a real network call to an IP-literal test host."""
    monkeypatch.setattr(fetch, "_check_robots", lambda url: True)


def test_private_loopback_link_local_and_reserved_targets_are_all_rejected() -> None:
    for url in (
        "http://127.0.0.1/",
        "http://127.0.0.1:8000/admin",
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata endpoint
        "http://10.0.0.5/",
        "http://172.16.0.1/",
        "http://192.168.1.1/",
        "http://[::1]/",
        "http://0.0.0.0/",
    ):
        with pytest.raises(fetch.UnsafeUrlError):
            fetch._validate_target(url)


def test_a_public_ip_literal_is_allowed() -> None:
    fetch._validate_target("http://8.8.8.8/")  # does not raise


def test_a_non_http_scheme_is_rejected() -> None:
    with pytest.raises(fetch.UnsafeUrlError):
        fetch._validate_target("file:///etc/passwd")
    with pytest.raises(fetch.UnsafeUrlError):
        fetch._validate_target("ftp://8.8.8.8/")


async def test_fetch_source_refuses_an_unsafe_url_before_any_network_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _unreachable(**kwargs: object) -> httpx.AsyncClient:
        raise AssertionError("must not attempt a connection for an unsafe URL")

    monkeypatch.setattr(fetch.httpx, "AsyncClient", _unreachable)

    result = await fetch.fetch_source(
        "http://169.254.169.254/latest/meta-data/iam/security-credentials/",
        timeout_seconds=5.0,
        max_chars=1000,
    )

    assert result.fetch_error is not None and result.fetch_error.startswith("unsafe_url:")
    assert result.content is None


# Captured before any test monkeypatches fetch.httpx.AsyncClient — that patch mutates the
# shared httpx module itself (fetch.httpx and this file's httpx are the same module object),
# so a factory that referred to `httpx.AsyncClient` by late-bound attribute lookup would end
# up calling itself once patched in.
_RealAsyncClient = httpx.AsyncClient


def _client_factory(handler):  # type: ignore[no-untyped-def]
    def factory(**kwargs: object) -> httpx.AsyncClient:
        return _RealAsyncClient(transport=httpx.MockTransport(handler), **kwargs)

    return factory


async def test_a_redirect_to_an_internal_address_is_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).startswith("http://8.8.8.8"):
            return httpx.Response(302, headers={"Location": "http://127.0.0.1/internal"})
        raise AssertionError(f"must not reach the redirect target: {request.url}")

    monkeypatch.setattr(fetch.httpx, "AsyncClient", _client_factory(handler))

    result = await fetch.fetch_source("http://8.8.8.8/start", timeout_seconds=5.0, max_chars=1000)

    assert result.fetch_error is not None and result.fetch_error.startswith("unsafe_url:")


async def test_a_redirect_loop_is_bounded_not_infinite(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(302, headers={"Location": "http://8.8.8.8/next"})

    monkeypatch.setattr(fetch.httpx, "AsyncClient", _client_factory(handler))

    result = await fetch.fetch_source("http://8.8.8.8/start", timeout_seconds=5.0, max_chars=1000)

    assert result.fetch_error is not None and result.fetch_error.startswith("unsafe_url:")
    assert calls["count"] == fetch.MAX_REDIRECTS


async def test_an_oversized_response_is_rejected_while_streaming_not_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    oversized = b"x" * (fetch.MAX_RESPONSE_BYTES + 1)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, content=oversized)

    monkeypatch.setattr(fetch.httpx, "AsyncClient", _client_factory(handler))

    result = await fetch.fetch_source("http://8.8.8.8/big", timeout_seconds=5.0, max_chars=1000)

    assert result.fetch_error is not None and result.fetch_error.startswith("response_too_large:")
    assert result.content is None
