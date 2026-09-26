import base64

import httpx
import pytest

from app.gmail import client


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode()


class _FakeHttpClient:
    """Duck-typed stand-in for httpx.AsyncClient — the client.py functions only ever call
    .get(url, headers=..., params=...), so a minimal fake covers them without touching a
    real transport."""

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


def _response(status_code: int, json_body: dict[str, object]) -> httpx.Response:
    return httpx.Response(
        status_code, json=json_body, request=httpx.Request("GET", "https://example.com")
    )


class _FakeHttpClientSequence:
    """Like _FakeHttpClient but returns a different response per call, in order — used to
    test retry behavior across multiple attempts."""

    def __init__(self, responses: list[httpx.Response]) -> None:
        self._responses = responses
        self.call_count = 0

    async def get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
    ) -> httpx.Response:
        response = self._responses[self.call_count]
        self.call_count += 1
        return response


def _rate_limit_response(status_code: int = 403) -> httpx.Response:
    return httpx.Response(
        status_code,
        json={"error": {"errors": [{"reason": "rateLimitExceeded"}]}},
        request=httpx.Request("GET", "https://example.com"),
    )


def test_is_rate_limit_response_detects_429() -> None:
    resp = httpx.Response(429, request=httpx.Request("GET", "https://example.com"))
    assert client._is_rate_limit_response(resp) is True


def test_is_rate_limit_response_detects_403_with_rate_limit_reason() -> None:
    assert client._is_rate_limit_response(_rate_limit_response()) is True


def test_is_rate_limit_response_does_not_flag_plain_permission_denied() -> None:
    resp = httpx.Response(
        403,
        json={"error": {"errors": [{"reason": "insufficientPermissions"}]}},
        request=httpx.Request("GET", "https://example.com"),
    )
    assert client._is_rate_limit_response(resp) is False


async def test_permission_denied_403_fails_immediately_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A tiny (but nonzero, so a real await asyncio.sleep(...) still happens) base delay —
    # keeps the test fast without touching the global asyncio module at all.
    monkeypatch.setattr(client, "_RETRY_BASE_DELAY_SECONDS", 0.001)

    denied = httpx.Response(
        403,
        json={"error": {"errors": [{"reason": "insufficientPermissions"}]}},
        request=httpx.Request("GET", "https://example.com"),
    )
    fake = _FakeHttpClientSequence([denied])

    with pytest.raises(client.GmailApiError):
        await client.get_profile(fake, "token")  # type: ignore[arg-type]

    assert fake.call_count == 1  # no retry for a non-rate-limit error


async def test_rate_limited_call_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(client, "_RETRY_BASE_DELAY_SECONDS", 0.001)

    fake = _FakeHttpClientSequence(
        [
            _rate_limit_response(),
            _rate_limit_response(),
            _response(200, {"emailAddress": "aziz@example.com"}),
        ]
    )

    profile = await client.get_profile(fake, "token")  # type: ignore[arg-type]

    assert profile["emailAddress"] == "aziz@example.com"
    assert fake.call_count == 3


async def test_rate_limited_call_gives_up_after_max_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(client, "_RETRY_BASE_DELAY_SECONDS", 0.001)

    fake = _FakeHttpClientSequence(
        [_rate_limit_response() for _ in range(client._MAX_RETRY_ATTEMPTS)]
    )

    with pytest.raises(client.GmailRateLimitError):
        await client.get_profile(fake, "token")  # type: ignore[arg-type]

    assert fake.call_count == client._MAX_RETRY_ATTEMPTS


async def test_get_profile_returns_parsed_json() -> None:
    fake = _FakeHttpClient(_response(200, {"emailAddress": "aziz@example.com", "historyId": "999"}))
    profile = await client.get_profile(fake, "token")  # type: ignore[arg-type]
    assert profile["emailAddress"] == "aziz@example.com"


async def test_get_profile_raises_on_error_status() -> None:
    fake = _FakeHttpClient(_response(401, {"error": "invalid_token"}))
    with pytest.raises(client.GmailApiError):
        await client.get_profile(fake, "token")  # type: ignore[arg-type]


async def test_list_message_ids_returns_ids_and_next_page_token() -> None:
    fake = _FakeHttpClient(
        _response(200, {"messages": [{"id": "a"}, {"id": "b"}], "nextPageToken": "page2"})
    )
    ids, next_token = await client.list_message_ids(fake, "token")  # type: ignore[arg-type]
    assert ids == ["a", "b"]
    assert next_token == "page2"


async def test_list_message_ids_empty_result() -> None:
    fake = _FakeHttpClient(_response(200, {}))
    ids, next_token = await client.list_message_ids(fake, "token")  # type: ignore[arg-type]
    assert ids == []
    assert next_token is None


async def test_list_history_returns_too_old_on_404() -> None:
    fake = _FakeHttpClient(httpx.Response(404, request=httpx.Request("GET", "https://example.com")))
    ids, next_token, too_old = await client.list_history(fake, "token", start_history_id="1")  # type: ignore[arg-type]
    assert too_old is True
    assert ids == []


async def test_list_history_returns_added_message_ids() -> None:
    fake = _FakeHttpClient(
        _response(
            200,
            {
                "history": [
                    {"messagesAdded": [{"message": {"id": "m1"}}]},
                    {"messagesAdded": [{"message": {"id": "m2"}}, {"message": {"id": "m3"}}]},
                ],
                "nextPageToken": None,
            },
        )
    )
    ids, next_token, too_old = await client.list_history(fake, "token", start_history_id="1")  # type: ignore[arg-type]
    assert ids == ["m1", "m2", "m3"]
    assert too_old is False


def _plain_text_message_payload() -> dict[str, object]:
    return {
        "id": "msg123",
        "threadId": "thread123",
        "snippet": "Hello preview",
        "internalDate": "1700000000000",
        "labelIds": ["INBOX", "UNREAD"],
        "payload": {
            "headers": [
                {"name": "Subject", "value": "Interview follow-up"},
                {"name": "From", "value": "recruiter@acme.com"},
                {"name": "To", "value": "aziz@example.com, cc@example.com"},
            ],
            "mimeType": "text/plain",
            "body": {"data": _b64("Thanks for chatting today.")},
        },
    }


def test_parse_message_extracts_plain_text_body() -> None:
    message = client.parse_message(_plain_text_message_payload())
    assert message.gmail_message_id == "msg123"
    assert message.thread_id == "thread123"
    assert message.subject == "Interview follow-up"
    assert message.from_address == "recruiter@acme.com"
    assert message.to_addresses == ["aziz@example.com", "cc@example.com"]
    assert message.body_text == "Thanks for chatting today."
    assert message.label_ids == ["INBOX", "UNREAD"]
    assert message.date is not None


def test_parse_message_prefers_plain_text_over_html_multipart() -> None:
    payload = {
        "id": "msg456",
        "threadId": "thread456",
        "snippet": "...",
        "payload": {
            "headers": [{"name": "Subject", "value": "Multipart"}],
            "mimeType": "multipart/alternative",
            "parts": [
                {"mimeType": "text/plain", "body": {"data": _b64("Plain version")}},
                {"mimeType": "text/html", "body": {"data": _b64("<p>HTML version</p>")}},
            ],
        },
    }
    message = client.parse_message(payload)
    assert message.body_text == "Plain version"


def test_parse_message_falls_back_to_html_when_no_plain_part() -> None:
    payload = {
        "id": "msg789",
        "threadId": "thread789",
        "snippet": "...",
        "payload": {
            "headers": [],
            "mimeType": "text/html",
            "body": {
                "data": _b64(
                    "<html><body><p>Only HTML here, long enough to extract.</p></body></html>"
                )
            },
        },
    }
    message = client.parse_message(payload)
    assert message.body_text is not None
    assert "Only HTML here" in message.body_text


def test_parse_message_handles_missing_body_gracefully() -> None:
    payload = {"id": "msg000", "threadId": "thread000", "snippet": "", "payload": {"headers": []}}
    message = client.parse_message(payload)
    assert message.body_text is None
    assert message.subject is None
    assert message.date is None


def test_parse_address_list_splits_and_strips() -> None:
    assert client._parse_address_list("a@x.com, b@y.com,c@z.com") == [
        "a@x.com",
        "b@y.com",
        "c@z.com",
    ]
    assert client._parse_address_list(None) == []
    assert client._parse_address_list("") == []


def test_get_header_is_case_insensitive() -> None:
    headers = [{"name": "Subject", "value": "Hi"}]
    assert client._get_header(headers, "subject") == "Hi"
    assert client._get_header(headers, "Missing") is None
