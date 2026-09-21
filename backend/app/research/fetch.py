"""Collect step: fetches a candidate URL and extracts its main content. Deterministic,
network-bound, no LLM involved. Pass/fail *judgment* on the result belongs to
app.research.verify — this module only reports what actually happened."""

import asyncio
import json
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


async def fetch_source(url: str, *, timeout_seconds: float, max_chars: int) -> FetchResult:
    allowed = await asyncio.to_thread(_check_robots, url)
    if not allowed:
        return FetchResult(url, None, None, None, None, "robots_disallowed")

    try:
        async with httpx.AsyncClient(
            follow_redirects=True, timeout=timeout_seconds, headers={"User-Agent": USER_AGENT}
        ) as client:
            response = await client.get(url)
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

    extracted_json = trafilatura.extract(
        response.text,
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
