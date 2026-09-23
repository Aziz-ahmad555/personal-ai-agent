"""Collect step: fetches a candidate URL and extracts its main content. Deterministic,
network-bound, no LLM involved. Pass/fail *judgment* on the result belongs to
app.research.verify — this module only reports what actually happened.

Both callers (app.research.pipeline for research sources, app.career.discovery for a job
posting captured by URL) hand this an address the *user* typed or a page linked to — never
something to trust as safe. See SSRF guards below: this is the one place in the app that
fetches an arbitrary external URL, so it's also the one place SSRF has to be stopped.
"""

import asyncio
import ipaddress
import json
import socket
from dataclasses import dataclass
from datetime import datetime
from urllib import robotparser
from urllib.parse import urlparse

import httpx
import trafilatura

from app.logging import get_logger

logger = get_logger(__name__)

USER_AGENT = (
    "PersonalAIAgent-ResearchBot/0.1 (single-user personal research assistant; "
    "respects robots.txt; not impersonating a browser)"
)

ALLOWED_SCHEMES = {"http", "https"}
# A public-looking URL can still resolve to (or redirect to) a private, loopback, or
# link-local address — including the cloud metadata address 169.254.169.254, which falls
# under link-local. Every hop (the initial URL and every redirect target) is resolved and
# checked before it's ever connected to.
MAX_REDIRECTS = 5
# Enforced while streaming, not after the fact: a malicious server can't exhaust memory by
# sending an oversized body before any content-based truncation would kick in.
MAX_RESPONSE_BYTES = 5 * 1024 * 1024


class UnsafeUrlError(RuntimeError):
    """The URL (or one of its redirects) resolves to a private/internal/reserved address, or
    uses a scheme other than http/https."""


class ResponseTooLargeError(RuntimeError):
    """The response body exceeded MAX_RESPONSE_BYTES — a distinct failure mode from an unsafe
    target: the address was fine, the server just sent more than we'll hold in memory."""


def _is_unsafe_ip(ip: str) -> bool:
    address = ipaddress.ip_address(ip)
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    )


def _validate_target(url: str) -> None:
    """Raises UnsafeUrlError if this URL must not be fetched. Resolution happens here (not
    left to httpx) specifically so the check runs against the same addresses that will
    actually be connected to."""
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise UnsafeUrlError(f"unsupported scheme: {parsed.scheme or '(none)'}")
    if not parsed.hostname:
        raise UnsafeUrlError("no hostname")
    try:
        addr_info = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror as exc:
        raise UnsafeUrlError(f"could not resolve host: {exc}") from exc
    resolved_ips = {str(info[4][0]) for info in addr_info}
    if any(_is_unsafe_ip(ip) for ip in resolved_ips):
        raise UnsafeUrlError(f"resolves to a non-public address: {sorted(resolved_ips)}")


@dataclass
class FetchResult:
    final_url: str
    http_status: int | None
    content: str | None
    title: str | None
    published_at: datetime | None
    fetch_error: str | None


def _check_robots(url: str) -> bool:
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    parser = robotparser.RobotFileParser()
    parser.set_url(robots_url)
    try:
        parser.read()
    except Exception:
        # If robots.txt itself is unreachable, don't block the fetch on that alone.
        return True
    return parser.can_fetch(USER_AGENT, url)


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return None


async def _read_capped(response: httpx.Response, *, max_bytes: int) -> bytes:
    """Reads the body while streaming, stopping the moment it would exceed max_bytes — a
    malicious server can't exhaust memory by sending an oversized response, since nothing
    beyond the cap is ever read into memory in the first place."""
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > max_bytes:
            raise ResponseTooLargeError(f"response exceeded {max_bytes} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


async def _fetch_following_redirects(
    client: httpx.AsyncClient, url: str, *, max_bytes: int
) -> tuple[httpx.Response, bytes]:
    """Follows redirects manually (httpx's own follow_redirects=True would connect to each
    hop before we get a chance to validate it) so every hop — not just the URL the user or a
    linked page originally gave us — is resolved and checked before it's connected to."""
    current = url
    for _ in range(MAX_REDIRECTS):
        await asyncio.to_thread(_validate_target, current)
        async with client.stream("GET", current) as response:
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    return response, b""
                current = str(response.url.join(location))
                continue
            body = await _read_capped(response, max_bytes=max_bytes)
            return response, body
    raise UnsafeUrlError("too many redirects")


async def fetch_source(url: str, *, timeout_seconds: float, max_chars: int) -> FetchResult:
    try:
        _validate_target(url)
    except UnsafeUrlError as exc:
        logger.warning("fetch_blocked_unsafe_url", url=url, error=str(exc))
        return FetchResult(url, None, None, None, None, f"unsafe_url:{exc}")

    allowed = await asyncio.to_thread(_check_robots, url)
    if not allowed:
        return FetchResult(url, None, None, None, None, "robots_disallowed")

    try:
        async with httpx.AsyncClient(
            follow_redirects=False, timeout=timeout_seconds, headers={"User-Agent": USER_AGENT}
        ) as client:
            response, body = await _fetch_following_redirects(
                client, url, max_bytes=MAX_RESPONSE_BYTES
            )
    except UnsafeUrlError as exc:
        logger.warning("fetch_blocked_unsafe_url", url=url, error=str(exc))
        return FetchResult(url, None, None, None, None, f"unsafe_url:{exc}")
    except ResponseTooLargeError as exc:
        logger.warning("fetch_response_too_large", url=url, error=str(exc))
        return FetchResult(url, None, None, None, None, f"response_too_large:{exc}")
    except httpx.HTTPError as exc:
        logger.warning("fetch_failed", url=url, error=str(exc))
        return FetchResult(url, None, None, None, None, f"request_failed:{exc}")

    final_url = str(response.url)
    status = response.status_code

    if status != 200:
        return FetchResult(final_url, status, None, None, None, f"http_{status}")

    content_type = response.headers.get("content-type", "")
    if "html" not in content_type and "text" not in content_type:
        error = f"unsupported_content_type:{content_type}"
        return FetchResult(final_url, status, None, None, None, error)

    text_body = body.decode(response.encoding or "utf-8", errors="replace")
    extracted_json = trafilatura.extract(
        text_body,
        output_format="json",
        with_metadata=True,
        include_comments=False,
        include_tables=False,
        favor_precision=True,
        url=final_url,
    )
    if not extracted_json:
        return FetchResult(final_url, response.status_code, None, None, None, "extraction_failed")

    data = json.loads(extracted_json)
    text = (data.get("text") or "").strip()[:max_chars]
    return FetchResult(
        final_url=final_url,
        http_status=response.status_code,
        content=text or None,
        title=data.get("title"),
        published_at=_parse_date(data.get("date")),
        fetch_error=None,
    )
