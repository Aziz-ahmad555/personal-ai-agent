"""A thin, async, read-only client for the parts of the Gmail REST API this integration
actually uses: profile, message listing, message fetching, and history (for incremental
sync). Hand-rolled over httpx rather than google-api-python-client because that SDK is
synchronous, and this codebase doesn't do blocking calls inside async request handlers.

Message parsing (_parse_message and friends) is kept as pure functions operating on plain
dicts, so it's fully unit-testable against fake Gmail API payloads with no network or
database involved.
"""

import asyncio
import base64
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
import trafilatura

from app.logging import get_logger

logger = get_logger(__name__)

GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"

_RATE_LIMIT_REASONS = {"rateLimitExceeded", "userRateLimitExceeded", "quotaExceeded"}
_MAX_RETRY_ATTEMPTS = 5
_RETRY_BASE_DELAY_SECONDS = 1.0


class GmailApiError(RuntimeError):
    """A Gmail API call failed for a reason other than a bad/expired token — that case is
    handled separately, by refreshing before each call (see sync.py)."""


class GmailRateLimitError(GmailApiError):
    """Gmail's per-user quota was hit — 403 with a rate-limit reason, or plain 429. Distinct
    from other GmailApiErrors because it's worth retrying with backoff rather than treating
    as a hard failure (a genuine 404/permission error never resolves itself by waiting)."""


@dataclass(frozen=True)
class GmailMessage:
    gmail_message_id: str
    thread_id: str
    subject: str | None
    from_address: str | None
    to_addresses: list[str]
    date: datetime | None
    snippet: str
    body_text: str | None
    label_ids: list[str]


def _auth_header(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


def _is_rate_limit_response(response: httpx.Response) -> bool:
    if response.status_code == 429:
        return True
    if response.status_code != 403:
        return False
    try:
        errors = response.json().get("error", {}).get("errors", [])
    except ValueError:
        return False
    return any(e.get("reason") in _RATE_LIMIT_REASONS for e in errors)


def _raise_for_status(response: httpx.Response) -> None:
    if response.status_code < 400:
        return
    logger.warning("gmail_api_error", status=response.status_code, url=str(response.url))
    if _is_rate_limit_response(response):
        raise GmailRateLimitError(
            f"Gmail API rate limit hit ({response.status_code}): {response.request.url}"
        )
    raise GmailApiError(
        f"Gmail API request failed ({response.status_code}): {response.request.url}"
    )


async def _get_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: dict[str, str],
    params: dict[str, str] | None = None,
) -> httpx.Response:
    """A single GET with exponential-backoff retry, but only for rate-limit responses —
    every other failure (bad request, permission denied, not found) fails immediately,
    since waiting and retrying can't fix those."""
    attempt = 0
    while True:
        response = await client.get(url, headers=headers, params=params)
        if not _is_rate_limit_response(response):
            return response
        attempt += 1
        if attempt >= _MAX_RETRY_ATTEMPTS:
            return response
        delay = _RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1))
        logger.warning(
            "gmail_api_rate_limited_retrying", url=url, attempt=attempt, delay_seconds=delay
        )
        await asyncio.sleep(delay)


async def get_profile(client: httpx.AsyncClient, access_token: str) -> dict[str, object]:
    response = await _get_with_retry(
        client, f"{GMAIL_API_BASE}/profile", headers=_auth_header(access_token)
    )
    _raise_for_status(response)
    result: dict[str, object] = response.json()
    return result


async def list_message_ids(
    client: httpx.AsyncClient,
    access_token: str,
    *,
    query: str | None = None,
    page_token: str | None = None,
) -> tuple[list[str], str | None]:
    params: dict[str, str] = {}
    if query:
        params["q"] = query
    if page_token:
        params["pageToken"] = page_token

    response = await _get_with_retry(
        client, f"{GMAIL_API_BASE}/messages", headers=_auth_header(access_token), params=params
    )
    _raise_for_status(response)
    data = response.json()
    ids = [m["id"] for m in data.get("messages", [])]
    return ids, data.get("nextPageToken")


async def get_message(
    client: httpx.AsyncClient, access_token: str, message_id: str
) -> GmailMessage:
    response = await _get_with_retry(
        client,
        f"{GMAIL_API_BASE}/messages/{message_id}",
        headers=_auth_header(access_token),
        params={"format": "full"},
    )
    _raise_for_status(response)
    return parse_message(response.json())


async def list_history(
    client: httpx.AsyncClient,
    access_token: str,
    *,
    start_history_id: str,
    page_token: str | None = None,
) -> tuple[list[str], str | None, bool]:
    """Returns (added_message_ids, next_page_token, history_id_too_old). A too-old history
    id (Gmail only retains ~1 week of history) means the caller must fall back to a fresh
    backfill rather than trying to page from a cursor Gmail no longer has."""
    params: dict[str, str] = {"startHistoryId": start_history_id, "historyTypes": "messageAdded"}
    if page_token:
        params["pageToken"] = page_token

    response = await _get_with_retry(
        client, f"{GMAIL_API_BASE}/history", headers=_auth_header(access_token), params=params
    )
    if response.status_code == 404:
        return [], None, True
    _raise_for_status(response)

    data = response.json()
    ids = [
        added["message"]["id"]
        for entry in data.get("history", [])
        for added in entry.get("messagesAdded", [])
    ]
    return ids, data.get("nextPageToken"), False


def _decode_part_data(data: str) -> str:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")


def _walk_parts(payload: dict[str, object]) -> list[dict[str, object]]:
    parts = [payload]
    sub_parts = payload.get("parts")
    if isinstance(sub_parts, list):
        for sub in sub_parts:
            if isinstance(sub, dict):
                parts.extend(_walk_parts(sub))
    return parts


def _extract_body_text(payload: dict[str, object]) -> str | None:
    parts = _walk_parts(payload)

    plain = next(
        (p for p in parts if p.get("mimeType") == "text/plain" and _part_data(p) is not None),
        None,
    )
    if plain is not None:
        data = _part_data(plain)
        assert data is not None
        return _decode_part_data(data)

    html_part = next(
        (p for p in parts if p.get("mimeType") == "text/html" and _part_data(p) is not None), None
    )
    if html_part is not None:
        data = _part_data(html_part)
        assert data is not None
        html = _decode_part_data(data)
        extracted = trafilatura.extract(html, include_comments=False, include_tables=False)
        return extracted if isinstance(extracted, str) else None

    return None


def _part_data(part: dict[str, object]) -> str | None:
    body = part.get("body")
    if isinstance(body, dict):
        data = body.get("data")
        if isinstance(data, str):
            return data
    return None


def _get_header(headers: list[dict[str, str]], name: str) -> str | None:
    for header in headers:
        if header.get("name", "").lower() == name.lower():
            return header.get("value")
    return None


def _parse_address_list(value: str | None) -> list[str]:
    if not value:
        return []
    return [addr.strip() for addr in value.split(",") if addr.strip()]


def parse_message(data: dict[str, object]) -> GmailMessage:
    """Pure: turns a Gmail `messages.get` (format=full) response into our storage shape."""
    payload = data.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    headers = payload.get("headers")
    headers = headers if isinstance(headers, list) else []

    internal_date = data.get("internalDate")
    date = (
        datetime.fromtimestamp(int(internal_date) / 1000, tz=UTC)
        if isinstance(internal_date, str) and internal_date.isdigit()
        else None
    )

    label_ids = data.get("labelIds")
    label_ids = label_ids if isinstance(label_ids, list) else []

    return GmailMessage(
        gmail_message_id=str(data["id"]),
        thread_id=str(data.get("threadId", data["id"])),
        subject=_get_header(headers, "Subject"),
        from_address=_get_header(headers, "From"),
        to_addresses=_parse_address_list(_get_header(headers, "To")),
        date=date,
        snippet=str(data.get("snippet", "")),
        body_text=_extract_body_text(payload),
        label_ids=[str(label) for label in label_ids],
    )
