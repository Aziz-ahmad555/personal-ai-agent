import json
from types import SimpleNamespace
from typing import Any

import pytest
from groq import APIConnectionError, APIStatusError

from app.research import llm


def _status_error(code: int) -> APIStatusError:
    # APIStatusError's real constructor wants an httpx.Response; the retry logic only reads
    # `.status_code`, so build the instance without one — same approach as
    # test_research_llm.py's Gemini fake, adapted to Groq's exception shape.
    exc = APIStatusError.__new__(APIStatusError)
    exc.status_code = code
    return exc


def _connection_error() -> APIConnectionError:
    return APIConnectionError.__new__(APIConnectionError)


def _tool_call_response(schema_name: str, arguments: str) -> SimpleNamespace:
    call = SimpleNamespace(function=SimpleNamespace(name=schema_name, arguments=arguments))
    message = SimpleNamespace(tool_calls=[call])
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class _FakeCompletions:
    def __init__(self, outcomes: list[Exception | SimpleNamespace]) -> None:
        self._outcomes = outcomes
        self.call_count = 0

    async def create(self, **_: Any) -> SimpleNamespace:
        outcome = self._outcomes[self.call_count]
        self.call_count += 1
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _provider(outcomes: list[Exception | SimpleNamespace]) -> tuple[Any, _FakeCompletions]:
    completions = _FakeCompletions(outcomes)
    provider = llm.GroqLLMProvider.__new__(llm.GroqLLMProvider)
    provider._client = SimpleNamespace(  # type: ignore[attr-defined]
        chat=SimpleNamespace(completions=completions)
    )
    provider._model = "test-model"  # type: ignore[attr-defined]
    return provider, completions


async def _call(provider: Any, schema_name: str = "x") -> dict[str, Any]:
    return await provider.generate_structured(
        system="s",
        user_message="u",
        schema_name=schema_name,
        schema_description="d",
        json_schema={"type": "object"},
        max_tokens=10,
    )


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm, "_RETRY_BASE_DELAY_SECONDS", 0.001)


async def test_successful_tool_call_is_parsed_as_json() -> None:
    provider, completions = _provider([_tool_call_response("x", json.dumps({"ok": True}))])

    assert await _call(provider) == {"ok": True}
    assert completions.call_count == 1


async def test_transient_503_retries_then_succeeds() -> None:
    provider, completions = _provider(
        [
            _status_error(503),
            _status_error(503),
            _tool_call_response("x", json.dumps({"ok": True})),
        ]
    )

    assert await _call(provider) == {"ok": True}
    assert completions.call_count == 3


async def test_rate_limit_429_is_retried() -> None:
    provider, completions = _provider(
        [_status_error(429), _tool_call_response("x", json.dumps({"ok": True}))]
    )

    assert await _call(provider) == {"ok": True}
    assert completions.call_count == 2


async def test_connection_error_is_treated_as_transient_and_retried() -> None:
    provider, completions = _provider(
        [_connection_error(), _tool_call_response("x", json.dumps({"ok": True}))]
    )

    assert await _call(provider) == {"ok": True}
    assert completions.call_count == 2


async def test_persistent_503_gives_up_after_max_attempts() -> None:
    provider, completions = _provider([_status_error(503) for _ in range(llm._MAX_RETRY_ATTEMPTS)])

    with pytest.raises(llm.LLMError):
        await _call(provider)

    assert completions.call_count == llm._MAX_RETRY_ATTEMPTS


async def test_non_transient_error_fails_immediately_without_retry() -> None:
    provider, completions = _provider([_status_error(400)])

    with pytest.raises(llm.LLMError):
        await _call(provider)

    assert completions.call_count == 1


async def test_non_api_exception_fails_immediately_without_retry() -> None:
    provider, completions = _provider([ValueError("boom")])

    with pytest.raises(llm.LLMError):
        await _call(provider)

    assert completions.call_count == 1


async def test_no_matching_tool_call_raises_llm_error() -> None:
    # The model called some other tool, or none at all — shouldn't happen since only one
    # tool is offered and it's forced, but must fail loudly rather than return {} silently.
    provider, _ = _provider([_tool_call_response("a_different_tool", json.dumps({"ok": True}))])

    with pytest.raises(llm.LLMError, match="did not include the expected tool call"):
        await _call(provider, schema_name="x")


async def test_invalid_json_in_tool_call_arguments_raises_llm_error() -> None:
    provider, _ = _provider([_tool_call_response("x", "not valid json")])

    with pytest.raises(llm.LLMError, match="weren't valid JSON"):
        await _call(provider)


def test_get_llm_provider_requires_a_key_for_groq() -> None:
    from app.config import Settings

    settings = Settings.model_construct(llm_provider="groq", groq_api_key=None)
    with pytest.raises(llm.LLMError, match="GROQ_API_KEY"):
        llm.get_llm_provider(settings)


def test_get_llm_provider_returns_a_groq_provider_when_configured() -> None:
    from app.config import Settings

    settings = Settings.model_construct(
        llm_provider="groq", groq_api_key="fake-key", groq_model="openai/gpt-oss-120b"
    )
    provider = llm.get_llm_provider(settings)
    assert isinstance(provider, llm.GroqLLMProvider)
