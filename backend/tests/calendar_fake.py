"""A fake Google Calendar for tests: canned responses keyed by request path (and query, when it
matters), so no test reaches the real API."""

from collections.abc import Callable
from urllib.parse import parse_qs, urlparse

import httpx

REAL_CLIENT = httpx.AsyncClient

Route = httpx.Response | Callable[[httpx.Request], httpx.Response]


def ok(data: object, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=data)


def event(
    event_id: str,
    *,
    summary: str = "Untitled",
    description: str | None = None,
    start: str = "2026-09-25T14:00:00Z",
    end: str = "2026-09-25T15:00:00Z",
    all_day: bool = False,
    attendees: list[dict] | None = None,
    organizer_email: str | None = None,
    status: str = "confirmed",
) -> dict:
    time_key = "date" if all_day else "dateTime"
    return {
        "id": event_id,
        "status": status,
        "summary": summary,
        "description": description,
        "htmlLink": f"https://calendar.google.com/event?eid={event_id}",
        "start": {time_key: start[:10] if all_day else start},
        "end": {time_key: end[:10] if all_day else end},
        "attendees": attendees or [],
        "organizer": {"email": organizer_email} if organizer_email else {},
    }


class FakeCalendar:
    def __init__(self) -> None:
        self.routes: dict[str, Route] = {}
        self.requests: list[str] = []
        self.queries: list[dict[str, list[str]]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        parsed = urlparse(str(request.url))
        self.requests.append(parsed.path)
        self.queries.append(parse_qs(parsed.query))
        route = self.routes.get(parsed.path)
        if route is None:
            return httpx.Response(404, json={"error": {"message": "not routed in the fake"}})
        return route(request) if callable(route) else route

    def client_factory(self) -> Callable[..., httpx.AsyncClient]:
        transport = httpx.MockTransport(self.handler)
        return lambda **kwargs: REAL_CLIENT(transport=transport)

    # --- canned scenarios ---------------------------------------------------------------

    def primary_calendar(self, email: str = "aziz@gmail.com") -> None:
        self.routes["/calendar/v3/calendars/primary"] = ok({"id": email, "summary": email})

    def events_page(
        self,
        events: list[dict],
        *,
        next_page_token: str | None = None,
        next_sync_token: str | None = None,
    ) -> None:
        body: dict[str, object] = {"items": events}
        if next_page_token:
            body["nextPageToken"] = next_page_token
        if next_sync_token:
            body["nextSyncToken"] = next_sync_token
        self.routes["/calendar/v3/calendars/primary/events"] = ok(body)
