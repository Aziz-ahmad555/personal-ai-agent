"""Phase 12 eval-harness instrumentation: record_llm_calls() must capture latency/tokens for
every real provider without changing generate_structured's own return value or behavior, and
must be a true no-op (zero effect) when nobody has opted in — this is shared instrumentation
code the running app also loads, not something the eval harness owns exclusively."""

import json
from types import SimpleNamespace
from typing import Any

from app.research import llm


def _gemini_provider(text: str, *, tokens_in: int, tokens_out: int) -> Any:
    async def generate_content(**_: Any) -> SimpleNamespace:
        return SimpleNamespace(
            text=text,
            usage_metadata=SimpleNamespace(
                prompt_token_count=tokens_in, candidates_token_count=tokens_out
            ),
        )

    provider = llm.GeminiLLMProvider.__new__(llm.GeminiLLMProvider)
    provider._client = SimpleNamespace(  # type: ignore[attr-defined]
        aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    )
    provider._model = "gemini-test"  # type: ignore[attr-defined]
    return provider


async def _call(provider: Any, schema_name: str = "x") -> dict[str, Any]:
    return await provider.generate_structured(
        system="s",
        user_message="u",
        schema_name=schema_name,
        schema_description="d",
        json_schema={"type": "object"},
        max_tokens=10,
    )


async def test_recording_is_a_true_no_op_when_nobody_opted_in() -> None:
    provider = _gemini_provider(json.dumps({"ok": True}), tokens_in=10, tokens_out=5)

    result = await _call(provider)

    assert result == {"ok": True}
    # Nothing to assert on directly (no handle to the records) — this test's only job is to
    # prove generate_structured still works and doesn't raise when unrecorded.


async def test_record_llm_calls_captures_provider_model_schema_and_tokens() -> None:
    provider = _gemini_provider(json.dumps({"ok": True}), tokens_in=42, tokens_out=17)

    records = llm.record_llm_calls()
    await _call(provider, schema_name="my_schema")

    assert len(records) == 1
    record = records[0]
    assert record.provider == "gemini"
    assert record.model == "gemini-test"
    assert record.schema_name == "my_schema"
    assert record.tokens_in == 42
    assert record.tokens_out == 17
    assert record.latency_ms >= 0


async def test_record_llm_calls_accumulates_across_multiple_calls() -> None:
    provider = _gemini_provider(json.dumps({"ok": True}), tokens_in=1, tokens_out=1)

    records = llm.record_llm_calls()
    await _call(provider, schema_name="first")
    await _call(provider, schema_name="second")

    assert [r.schema_name for r in records] == ["first", "second"]


async def test_anthropic_provider_is_recorded_with_its_own_usage_fields() -> None:
    async def create(**_: Any) -> SimpleNamespace:
        return SimpleNamespace(
            content=[
                SimpleNamespace(type="tool_use", name="x", input={"ok": True}),
            ],
            usage=SimpleNamespace(input_tokens=7, output_tokens=3),
        )

    provider = llm.AnthropicLLMProvider.__new__(llm.AnthropicLLMProvider)
    provider._client = SimpleNamespace(  # type: ignore[attr-defined]
        messages=SimpleNamespace(create=create)
    )
    provider._model = "claude-test"  # type: ignore[attr-defined]

    records = llm.record_llm_calls()
    await _call(provider)

    assert len(records) == 1
    assert records[0].provider == "anthropic"
    assert records[0].tokens_in == 7
    assert records[0].tokens_out == 3


async def test_groq_provider_is_recorded_with_its_own_usage_fields() -> None:
    async def create(**_: Any) -> SimpleNamespace:
        args = json.dumps({"ok": True})
        call = SimpleNamespace(function=SimpleNamespace(name="x", arguments=args))
        message = SimpleNamespace(tool_calls=[call])
        return SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
            usage=SimpleNamespace(prompt_tokens=11, completion_tokens=4),
        )

    provider = llm.GroqLLMProvider.__new__(llm.GroqLLMProvider)
    provider._client = SimpleNamespace(  # type: ignore[attr-defined]
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    provider._model = "groq-test"  # type: ignore[attr-defined]

    records = llm.record_llm_calls()
    await _call(provider)

    assert len(records) == 1
    assert records[0].provider == "groq"
    assert records[0].tokens_in == 11
    assert records[0].tokens_out == 4
