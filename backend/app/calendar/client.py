"""A thin, async, read-only client for the parts of the Google Calendar REST API this
integration uses. Only GET requests exist in this module; there is no write helper to call
by mistake — a test asserts that (see tests/test_calendar_oauth.py).
"""

import httpx

CALENDAR_API_BASE = "https://www.googleapis.com/calendar/v3"


class CalendarApiError(RuntimeError):
    """A Calendar API call failed for a reason other than a bad/expired token — that case
    is handled separately, by refreshing before each call (see service.py)."""


class CalendarAuthError(CalendarApiError):
    """Google rejected the token (401): expired, revoked or wrong."""


def _auth_header(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


async def get_primary_calendar(client: httpx.AsyncClient, access_token: str) -> dict[str, object]:
    """The user's primary calendar. Its `id` is their Google account email — the same
    convention Gmail's callback uses `/profile`'s emailAddress for, this is Calendar's
    equivalent proof of which account was actually granted."""
    response = await client.get(
        f"{CALENDAR_API_BASE}/calendars/primary", headers=_auth_header(access_token)
    )
    if response.status_code == 401:
        raise CalendarAuthError("Google rejected the access token.")
    if response.status_code != 200:
        raise CalendarApiError(f"Calendar API request failed ({response.status_code}).")
    result: dict[str, object] = response.json()
    return result
