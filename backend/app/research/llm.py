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
from typing import Any, Protocol, cast

from app.config import Settings
from app.logging import get_logger

logger = get_logger(__name__)

# Gemini overloads (503) and rate limits (429) are usually gone within seconds; every other
# failure (bad request, bad key, safety block) is not something waiting can fix.
_TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}
_MAX_RETRY_ATTEMPTS = 4
_RETRY_BASE_DELAY_SECONDS = 2.0


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
            return cast(dict[str, Any], json.loads(text))
        except json.JSONDecodeError as exc:
            raise LLMError(f"Gemini returned output that wasn't valid JSON: {exc}") from exc


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
                return dict(block.input)

        raise LLMError("Anthropic response did not include the expected tool_use block.")


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

    raise LLMError(f"Unknown LLM_PROVIDER setting: {settings.llm_provider!r}")
