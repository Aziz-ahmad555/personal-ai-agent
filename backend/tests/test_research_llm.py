from types import SimpleNamespace
from typing import Any

import pytest
from google.genai import errors

from app.research import llm


def _api_error(cls: type[errors.APIError], code: int) -> errors.APIError:
    # APIError's real constructor wants an HTTP response object; the retry logic only reads
    # `.code`, so build the instance without one.
    exc = cls.__new__(cls)
    exc.code = code
    return exc


class _FakeModels:
    def __init__(self, outcomes: list[Exception | SimpleNamespace]) -> None:
        self._outcomes = outcomes
        self.call_count = 0

    async def generate_content(self, **_: Any) -> SimpleNamespace:
        outcome = self._outcomes[self.call_count]
        self.call_count += 1
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _provider(outcomes: list[Exception | SimpleNamespace]) -> tuple[Any, _FakeModels]:
    models = _FakeModels(outcomes)
    provider = llm.GeminiLLMProvider.__new__(llm.GeminiLLMProvider)
    provider._client = SimpleNamespace(aio=SimpleNamespace(models=models))  # type: ignore[attr-defined]
    provider._model = "test-model"  # type: ignore[attr-defined]
    return provider, models


async def _call(provider: Any) -> dict[str, Any]:
    return await provider.generate_structured(
        system="s",
        user_message="u",
        schema_name="x",
        schema_description="d",
        json_schema={"type": "object"},
        max_tokens=10,
    )


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm, "_RETRY_BASE_DELAY_SECONDS", 0.001)


async def test_transient_503_retries_then_succeeds() -> None:
    provider, models = _provider(
        [
            _api_error(errors.ServerError, 503),
            _api_error(errors.ServerError, 503),
            SimpleNamespace(text='{"ok": true}'),
        ]
    )

    assert await _call(provider) == {"ok": True}
    assert models.call_count == 3


async def test_persistent_503_gives_up_after_max_attempts() -> None:
    provider, models = _provider(
        [_api_error(errors.ServerError, 503) for _ in range(llm._MAX_RETRY_ATTEMPTS)]
    )

    with pytest.raises(llm.LLMError):
        await _call(provider)

    assert models.call_count == llm._MAX_RETRY_ATTEMPTS


async def test_rate_limit_429_is_retried() -> None:
    provider, models = _provider(
        [_api_error(errors.ClientError, 429), SimpleNamespace(text='{"ok": true}')]
    )

    assert await _call(provider) == {"ok": True}
    assert models.call_count == 2


async def test_non_transient_error_fails_immediately_without_retry() -> None:
    provider, models = _provider([_api_error(errors.ClientError, 400)])

    with pytest.raises(llm.LLMError):
        await _call(provider)

    assert models.call_count == 1


async def test_non_api_exception_fails_immediately_without_retry() -> None:
    provider, models = _provider([ConnectionError("boom")])

    with pytest.raises(llm.LLMError):
        await _call(provider)

    assert models.call_count == 1
