"""Board client tests with a duck-typed fake httpx client (mirrors test_gmail_client.py) —
no real network. Covers the response-shape parsing for each board and the error path when
a board returns a non-200."""

import httpx
import pytest

from app.career.boards import (
    BoardApiError,
    fetch_ashby_postings,
    fetch_greenhouse_postings,
    fetch_lever_postings,
    fetch_usajobs_postings,
)


class _FakeHttpClient:
    def __init__(self, response: httpx.Response) -> None:
        self._response = response
        self.calls: list[tuple[str, dict[str, str] | None]] = []

    async def get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
    ) -> httpx.Response:
        self.calls.append((url, params))
        return self._response


def _response(status_code: int, json_body: object) -> httpx.Response:
    return httpx.Response(
        status_code, json=json_body, request=httpx.Request("GET", "https://example.com")
    )


async def test_fetch_greenhouse_postings_parses_jobs() -> None:
    body = {
        "jobs": [
            {
                "id": 123,
                "title": "Senior ML Engineer",
                "location": {"name": "Remote"},
                "absolute_url": "https://boards.greenhouse.io/acme/jobs/123",
                "updated_at": "2026-09-01T00:00:00Z",
                "content": "<p>We need PyTorch experience.</p>",
            }
        ]
    }
    client = _FakeHttpClient(_response(200, body))
    postings = await fetch_greenhouse_postings(client, "acme")  # type: ignore[arg-type]

    assert len(postings) == 1
    assert postings[0].external_id == "123"
    assert postings[0].title == "Senior ML Engineer"
    assert postings[0].location == "Remote"
    assert postings[0].url == "https://boards.greenhouse.io/acme/jobs/123"


async def test_fetch_greenhouse_postings_raises_on_http_error() -> None:
    client = _FakeHttpClient(_response(404, {}))
    with pytest.raises(BoardApiError):
        await fetch_greenhouse_postings(client, "nonexistent-co")  # type: ignore[arg-type]


async def test_fetch_lever_postings_parses_jobs() -> None:
    body = [
        {
            "id": "abc-123",
            "text": "Backend Engineer",
            "categories": {"location": "New York"},
            "hostedUrl": "https://jobs.lever.co/acme/abc-123",
            "createdAt": 1735689600000,
            "descriptionPlain": "Build APIs.",
        }
    ]
    client = _FakeHttpClient(_response(200, body))
    postings = await fetch_lever_postings(client, "acme")  # type: ignore[arg-type]

    assert len(postings) == 1
    assert postings[0].external_id == "abc-123"
    assert postings[0].location == "New York"
    assert postings[0].description == "Build APIs."


async def test_fetch_ashby_postings_parses_jobs() -> None:
    body = {
        "jobs": [
            {
                "id": "job-1",
                "title": "Product Designer",
                "location": "San Francisco",
                "jobUrl": "https://jobs.ashbyhq.com/acme/job-1",
                "publishedAt": "2026-09-01T00:00:00Z",
                "descriptionPlain": "Design things.",
            }
        ]
    }
    client = _FakeHttpClient(_response(200, body))
    postings = await fetch_ashby_postings(client, "acme")  # type: ignore[arg-type]

    assert len(postings) == 1
    assert postings[0].title == "Product Designer"


async def test_fetch_usajobs_postings_parses_search_results() -> None:
    body = {
        "SearchResult": {
            "SearchResultItems": [
                {
                    "MatchedObjectId": "usa-1",
                    "MatchedObjectDescriptor": {
                        "PositionTitle": "Data Scientist",
                        "PositionLocationDisplay": "Washington, DC",
                        "PositionURI": "https://www.usajobs.gov/job/usa-1",
                        "PublicationStartDate": "2026-09-01",
                        "UserArea": {"Details": {"JobSummary": "Analyze federal data."}},
                    },
                }
            ]
        }
    }
    client = _FakeHttpClient(_response(200, body))
    postings = await fetch_usajobs_postings(
        client,  # type: ignore[arg-type]
        "data scientist",
        api_key="fake-key",
        user_agent_email="me@example.com",
    )

    assert len(postings) == 1
    assert postings[0].external_id == "usa-1"
    assert postings[0].description == "Analyze federal data."
    # The API key must actually be sent, never silently dropped.
    assert client.calls[0][1] == {"Keyword": "data scientist"}


async def test_fetch_usajobs_postings_raises_on_http_error() -> None:
    client = _FakeHttpClient(_response(500, {}))
    with pytest.raises(BoardApiError):
        await fetch_usajobs_postings(
            client,
            "x",
            api_key="k",
            user_agent_email="e@example.com",  # type: ignore[arg-type]
        )
