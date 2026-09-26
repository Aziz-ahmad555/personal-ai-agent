"""LLM abstraction for the Research Engine's two LLM-assisted steps (claim extraction,
report drafting). Mirrors app.research.search.SearchProvider: a small Protocol so the
vendor can be swapped (Gemini today, Anthropic/OpenAI available) without touching
extraction.py or report.py, which only ever see `generate_structured()`.

Every implementation must return the parsed JSON object matching the given schema, or
raise LLMError — never partial/free-text output standing in for structured data. Which
provider is active is a config decision (`settings.llm_provider`), not a runtime guess.
"""

import asyncio
import json
import time
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Protocol, cast

from app.config import Settings
from app.logging import get_logger

logger = get_logger(__name__)

# Gemini overloads (503) and rate limits (429) are usually gone within seconds; every other
# failure (bad request, bad key, safety block) is not something waiting can fix.
_TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}
_MAX_RETRY_ATTEMPTS = 4
_RETRY_BASE_DELAY_SECONDS = 2.0


@dataclass(frozen=True)
class LLMCallRecord:
    """One real generate_structured() call, for the eval harness's cost/latency/token
    report — nothing in the running app reads this; it's opt-in via record_llm_calls()."""

    provider: str
    model: str
    schema_name: str
    latency_ms: float
    tokens_in: int | None
    tokens_out: int | None


# None (the default) means "nobody's listening" — every provider's recording call becomes a
# no-op, so this has zero effect on normal request handling. The eval harness opts in per task
# via record_llm_calls(), so concurrent tasks (and concurrent requests generally) each get
# their own list rather than one shared one racing across coroutines/tasks.
_call_records: ContextVar[list[LLMCallRecord] | None] = ContextVar("_call_records", default=None)


def record_llm_calls() -> list[LLMCallRecord]:
    """Starts recording every generate_structured() call made from this point on, within
    this asyncio task (and tasks spawned from it — ContextVar propagates on task creation,
    not across independently-scheduled tasks). Returns the (initially empty) list that fills
    up as calls happen — read it after the task completes."""
    records: list[LLMCallRecord] = []
    _call_records.set(records)
    return records


def _record(
    *,
    provider: str,
    model: str,
    schema_name: str,
    latency_ms: float,
    tokens_in: int | None,
    tokens_out: int | None,
) -> None:
    records = _call_records.get()
    if records is not None:
        records.append(
            LLMCallRecord(
                provider=provider,
                model=model,
                schema_name=schema_name,
                latency_ms=latency_ms,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
            )
        )


class LLMError(RuntimeError):
    """Raised when a structured-output call cannot run at all (missing key, API/network
    failure, or the model didn't return valid structured output) — the caller must treat
    this as a hard stop for the step, never fall back to unstructured prose."""


class LLMProvider(Protocol):
    async def generate_structured(
        self,
        *,
        system: str,
        user_message: str,
        schema_name: str,
        schema_description: str,
        json_schema: dict[str, Any],
        max_tokens: int,
    ) -> dict[str, Any]: ...


class GeminiLLMProvider:
    """Uses Gemini's native structured-output mode (response_schema + JSON mime type)
    rather than function-calling — for our use case ("return JSON matching this shape")
    that's the more direct fit and needs no tool-choice forcing."""

    def __init__(self, api_key: str, model: str) -> None:
        from google import genai

        self._client = genai.Client(api_key=api_key)
        self._model = model

    async def generate_structured(
        self,
        *,
        system: str,
        user_message: str,
        schema_name: str,
        schema_description: str,
        json_schema: dict[str, Any],
        max_tokens: int,
    ) -> dict[str, Any]:
        from google.genai import errors, types

        start = time.perf_counter()
        attempt = 0
        while True:
            attempt += 1
            try:
                response = await self._client.aio.models.generate_content(
                    model=self._model,
                    contents=user_message,
                    config=types.GenerateContentConfig(
                        system_instruction=system,
                        response_mime_type="application/json",
                        response_schema=json_schema,
                        max_output_tokens=max_tokens,
                    ),
                )
                break
            except Exception as exc:
                transient = (
                    isinstance(exc, errors.APIError) and exc.code in _TRANSIENT_STATUS_CODES
                )
                if not transient or attempt >= _MAX_RETRY_ATTEMPTS:
                    logger.warning(
                        "gemini_generate_failed",
                        schema_name=schema_name,
                        attempts=attempt,
                        error=str(exc),
                    )
                    raise LLMError(f"Gemini call failed: {exc}") from exc
                delay = _RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1))
                logger.warning(
                    "gemini_transient_error_retrying",
                    schema_name=schema_name,
                    attempt=attempt,
                    delay_seconds=delay,
                    error=str(exc),
                )
                await asyncio.sleep(delay)

        text = getattr(response, "text", None)
        if not text:
            raise LLMError("Gemini returned no structured output.")
        try:
            parsed = cast(dict[str, Any], json.loads(text))
        except json.JSONDecodeError as exc:
            raise LLMError(f"Gemini returned output that wasn't valid JSON: {exc}") from exc

        usage = getattr(response, "usage_metadata", None)
        _record(
            provider="gemini",
            model=self._model,
            schema_name=schema_name,
            latency_ms=(time.perf_counter() - start) * 1000,
            tokens_in=getattr(usage, "prompt_token_count", None) if usage else None,
            tokens_out=getattr(usage, "candidates_token_count", None) if usage else None,
        )
        return parsed


class AnthropicLLMProvider:
    """Uses forced tool-use (tool_choice pinned to the one tool) as Claude's structured-
    output mechanism."""

    def __init__(self, api_key: str, model: str) -> None:
        from anthropic import AsyncAnthropic

        self._client = AsyncAnthropic(api_key=api_key)
        self._model = model

    async def generate_structured(
        self,
        *,
        system: str,
        user_message: str,
        schema_name: str,
        schema_description: str,
        json_schema: dict[str, Any],
        max_tokens: int,
    ) -> dict[str, Any]:
        start = time.perf_counter()
        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                system=system,
                tools=[
                    {
                        "name": schema_name,
                        "description": schema_description,
                        "input_schema": json_schema,
                    }
                ],
                tool_choice={"type": "tool", "name": schema_name},
                messages=[{"role": "user", "content": user_message}],
            )
        except Exception as exc:
            logger.warning("anthropic_generate_failed", schema_name=schema_name, error=str(exc))
            raise LLMError(f"Anthropic call failed: {exc}") from exc

        for block in response.content:
            if block.type == "tool_use" and block.name == schema_name:
                usage = getattr(response, "usage", None)
                _record(
                    provider="anthropic",
                    model=self._model,
                    schema_name=schema_name,
                    latency_ms=(time.perf_counter() - start) * 1000,
                    tokens_in=getattr(usage, "input_tokens", None) if usage else None,
                    tokens_out=getattr(usage, "output_tokens", None) if usage else None,
                )
                return dict(block.input)

        raise LLMError("Anthropic response did not include the expected tool_use block.")


class GroqLLMProvider:
    """Groq's API is OpenAI-compatible (chat completions + function/tool calling), not
    Gemini's or Anthropic's own shapes. Uses forced tool-use as the structured-output
    mechanism — the same JSON-shaping trick AnthropicLLMProvider already uses in this file
    — rather than Groq's looser `response_format: json_object` mode, which only guarantees
    valid JSON, not conformance to our schema."""

    def __init__(self, api_key: str, model: str) -> None:
        from groq import AsyncGroq

        self._client = AsyncGroq(api_key=api_key)
        self._model = model

    async def generate_structured(
        self,
        *,
        system: str,
        user_message: str,
        schema_name: str,
        schema_description: str,
        json_schema: dict[str, Any],
        max_tokens: int,
    ) -> dict[str, Any]:
        from groq import APIConnectionError, APIStatusError

        start = time.perf_counter()
        attempt = 0
        while True:
            attempt += 1
            try:
                response = await self._client.chat.completions.create(
                    model=self._model,
                    max_tokens=max_tokens,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user_message},
                    ],
                    tools=[
                        {
                            "type": "function",
                            "function": {
                                "name": schema_name,
                                "description": schema_description,
                                "parameters": json_schema,
                            },
                        }
                    ],
                    tool_choice={"type": "function", "function": {"name": schema_name}},
                )
                break
            except Exception as exc:
                # A connection-level failure (no response at all) has no status_code to
                # check — treated the same as a transient 5xx, since retrying is the right
                # move either way. Anything else (bad request, auth, a real APIStatusError
                # with a non-transient code) is not something waiting can fix.
                if isinstance(exc, APIConnectionError):
                    transient = True
                elif isinstance(exc, APIStatusError):
                    transient = exc.status_code in _TRANSIENT_STATUS_CODES
                else:
                    transient = False
                if not transient or attempt >= _MAX_RETRY_ATTEMPTS:
                    logger.warning(
                        "groq_generate_failed",
                        schema_name=schema_name,
                        attempts=attempt,
                        error=str(exc),
                    )
                    raise LLMError(f"Groq call failed: {exc}") from exc
                delay = _RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1))
                logger.warning(
                    "groq_transient_error_retrying",
                    schema_name=schema_name,
                    attempt=attempt,
                    delay_seconds=delay,
                    error=str(exc),
                )
                await asyncio.sleep(delay)

        message = response.choices[0].message
        tool_calls = message.tool_calls or []
        for call in tool_calls:
            if call.function.name == schema_name:
                try:
                    parsed = cast(dict[str, Any], json.loads(call.function.arguments))
                except json.JSONDecodeError as exc:
                    raise LLMError(
                        f"Groq returned tool-call arguments that weren't valid JSON: {exc}"
                    ) from exc

                usage = getattr(response, "usage", None)
                _record(
                    provider="groq",
                    model=self._model,
                    schema_name=schema_name,
                    latency_ms=(time.perf_counter() - start) * 1000,
                    tokens_in=getattr(usage, "prompt_tokens", None) if usage else None,
                    tokens_out=getattr(usage, "completion_tokens", None) if usage else None,
                )
                return parsed

        raise LLMError("Groq response did not include the expected tool call.")


def get_llm_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "gemini":
        if not settings.gemini_api_key:
            raise LLMError(
                "GEMINI_API_KEY is not set — the Research Engine cannot extract claims or "
                "draft a report without it. Add it to .env."
            )
        return GeminiLLMProvider(api_key=settings.gemini_api_key, model=settings.gemini_model)

    if settings.llm_provider == "anthropic":
        if not settings.anthropic_api_key:
            raise LLMError(
                "ANTHROPIC_API_KEY is not set — the Research Engine cannot extract claims or "
                "draft a report without it. Add it to .env."
            )
        return AnthropicLLMProvider(
            api_key=settings.anthropic_api_key, model=settings.anthropic_model
        )

    if settings.llm_provider == "groq":
        if not settings.groq_api_key:
            raise LLMError(
                "GROQ_API_KEY is not set — the Research Engine cannot extract claims or "
                "draft a report without it. Add it to .env."
            )
        return GroqLLMProvider(api_key=settings.groq_api_key, model=settings.groq_model)

    raise LLMError(f"Unknown LLM_PROVIDER setting: {settings.llm_provider!r}")
