"""A thin, async, read-only client for the parts of the Google Calendar REST API this
integration uses. Only GET requests exist in this module; there is no write helper to call
by mistake — a test asserts that (see tests/test_calendar_oauth.py).
"""

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx

from app.logging import get_logger

logger = get_logger(__name__)

CALENDAR_API_BASE = "https://www.googleapis.com/calendar/v3"

# Mirrors app.research.llm's retry shape: a rate limit (429) or server-side overload
# (5xx) is usually gone within seconds; a 401/410 never resolves itself by waiting, so
# those are left for _raise_for_status to turn into their own typed errors immediately.
_TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}
_MAX_RETRY_ATTEMPTS = 4
_RETRY_BASE_DELAY_SECONDS = 2.0


class CalendarApiError(RuntimeError):
    """A Calendar API call failed for a reason other than a bad/expired token — that case
    is handled separately, by refreshing before each call (see service.py)."""


class CalendarAuthError(CalendarApiError):
    """Google rejected the token (401): expired, revoked or wrong."""


class SyncTokenExpiredError(CalendarApiError):
    """Google no longer has history back to our stored sync token (410 Gone,
    fullSyncRequired) — the caller must fall back to a fresh full sync."""


def _auth_header(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


async def _get_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: dict[str, str],
    params: dict[str, str] | None = None,
) -> httpx.Response:
    """A single GET with exponential-backoff retry, but only for transient failures — a
    401 or 410 is returned as-is on the first attempt, since _raise_for_status must turn
    those into their own typed errors right away rather than being retried."""
    attempt = 0
    while True:
        response = await client.get(url, headers=headers, params=params)
        attempt += 1
        if response.status_code not in _TRANSIENT_STATUS_CODES or attempt >= _MAX_RETRY_ATTEMPTS:
            return response
        delay = _RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1))
        logger.warning(
            "calendar_api_transient_error_retrying",
            url=url,
            status=response.status_code,
            attempt=attempt,
            delay_seconds=delay,
        )
        await asyncio.sleep(delay)


def _raise_for_status(response: httpx.Response) -> None:
    if response.status_code == 401:
        raise CalendarAuthError("Google rejected the access token.")
    if response.status_code == 410:
        raise SyncTokenExpiredError("The stored sync token is no longer valid.")
    if response.status_code != 200:
        raise CalendarApiError(f"Calendar API request failed ({response.status_code}).")


async def get_primary_calendar(client: httpx.AsyncClient, access_token: str) -> dict[str, object]:
    """The user's primary calendar. Its `id` is their Google account email — the same
    convention Gmail's callback uses `/profile`'s emailAddress for, this is Calendar's
    equivalent proof of which account was actually granted."""
    response = await _get_with_retry(
        client, f"{CALENDAR_API_BASE}/calendars/primary", headers=_auth_header(access_token)
    )
    _raise_for_status(response)
    result: dict[str, object] = response.json()
    return result


@dataclass(frozen=True)
class EventsPage:
    events: list[dict[str, Any]]
    next_page_token: str | None
    # Only ever set on the final page of a request that had no next_page_token — this is
    # what a later incremental sync starts from.
    next_sync_token: str | None


async def list_events(
    client: httpx.AsyncClient,
    access_token: str,
    *,
    time_min: str | None = None,
    time_max: str | None = None,
    sync_token: str | None = None,
    page_token: str | None = None,
    max_results: int = 250,
) -> EventsPage:
    """One page of events on the primary calendar. Either (`time_min`, `time_max`) for a full
    window list, or `sync_token` for an incremental one since the last full list — Google's
    API doesn't allow combining a time window with a sync token. `singleEvents=true` expands
    recurring events into their individual instances, since it's each instance's own time
    that matters for interview/deadline detection, not the recurrence rule."""
    params: dict[str, str] = {"singleEvents": "true", "maxResults": str(max_results)}
    if sync_token:
        params["syncToken"] = sync_token
    else:
        if time_min:
            params["timeMin"] = time_min
        if time_max:
            params["timeMax"] = time_max
        params["orderBy"] = "startTime"
    if page_token:
        params["pageToken"] = page_token

    response = await _get_with_retry(
        client,
        f"{CALENDAR_API_BASE}/calendars/primary/events",
        headers=_auth_header(access_token),
        params=params,
    )
    _raise_for_status(response)
    data = response.json()
    items = data.get("items", [])
    if not isinstance(items, list):
        raise CalendarApiError("Calendar API returned an unexpected events response.")
    return EventsPage(
        events=[item for item in items if isinstance(item, dict)],
        next_page_token=data.get("nextPageToken"),
        next_sync_token=data.get("nextSyncToken"),
    )
