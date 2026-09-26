"""app.research.llm.SpendGuardedProvider: the runtime enforcement half of Settings'
max_tokens_per_task / daily_spend_cap_usd. Gated behind start_cost_guarded_task() (see
app.core.scheduler and every *_in_background function for where the real app calls it) —
deliberately not on by default, so an eval harness run (which uses its own record_llm_calls()
for cost *reporting*, never start_cost_guarded_task()) can never trip these limits or write
into the production LLMSpendLedger. A refused call never reaches the inner provider and is
never ledgered; a real call is ledgered only after it actually succeeds."""

import types
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.research import llm
from app.research.cost_models import LLMSpendLedger


class _FakeInnerProvider:
    def __init__(self, tokens_in: int = 100, tokens_out: int = 100) -> None:
        self.call_count = 0
        self._tokens_in = tokens_in
        self._tokens_out = tokens_out

    async def generate_structured(self, **_: Any) -> dict[str, Any]:
        self.call_count += 1
        # Mirrors what a real provider does on success: record usage if a recorder is
        # active for this task, exactly like llm.GeminiLLMProvider/etc. do via _record().
        llm._record(
            provider="fake",
            model="claude-haiku-4-5-20251001",
            schema_name="x",
            latency_ms=1.0,
            tokens_in=self._tokens_in,
            tokens_out=self._tokens_out,
        )
        return {"ok": True}


def _settings(*, max_tokens_per_task: int = 200_000, daily_spend_cap_usd: float = 5.0) -> Any:
    return types.SimpleNamespace(
        max_tokens_per_task=max_tokens_per_task, daily_spend_cap_usd=daily_spend_cap_usd
    )


async def _call(provider: llm.SpendGuardedProvider) -> dict[str, Any]:
    return await provider.generate_structured(
        system="s",
        user_message="u",
        schema_name="x",
        schema_description="d",
        json_schema={"type": "object"},
        max_tokens=10,
    )


async def test_refuses_once_this_tasks_own_tokens_reach_the_per_task_limit() -> None:
    llm.start_cost_guarded_task()
    inner = _FakeInnerProvider(tokens_in=100, tokens_out=100)  # 200 tokens/call
    guarded = llm.SpendGuardedProvider(inner, _settings(max_tokens_per_task=200))

    await _call(guarded)  # nothing spent yet when this call is checked — allowed
    assert inner.call_count == 1

    with pytest.raises(llm.LLMError, match="per-task limit"):
        await _call(guarded)  # the task already has 200/200 tokens — refused before calling inner

    assert inner.call_count == 1  # the refused call never reached the inner provider


async def test_without_enabling_the_cost_guard_it_is_a_complete_passthrough(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """start_cost_guarded_task() was never called for this "task" — matches eval code, or a
    real call site that forgot to wire up a task boundary. Without it, the guard enforces
    neither limit and never touches LLMSpendLedger at all — this is what keeps an eval
    --live run from tripping the production daily cap or writing into its ledger."""
    inner = _FakeInnerProvider(tokens_in=10**9, tokens_out=10**9)
    guarded = llm.SpendGuardedProvider(
        inner, _settings(max_tokens_per_task=1, daily_spend_cap_usd=0.0)
    )

    result = await _call(guarded)

    assert result == {"ok": True}
    assert inner.call_count == 1
    async with session_factory() as db:
        assert (await db.execute(select(LLMSpendLedger))).first() is None


async def test_refuses_once_todays_ledger_total_reaches_the_daily_cap(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    llm.start_cost_guarded_task()
    async with session_factory() as db:
        db.add(
            LLMSpendLedger(
                provider="fake", model="x", tokens_in=1, tokens_out=1, estimated_cost_usd=5.0
            )
        )
        await db.commit()

    inner = _FakeInnerProvider()
    guarded = llm.SpendGuardedProvider(inner, _settings(daily_spend_cap_usd=5.0))

    with pytest.raises(llm.LLMError, match="daily cap"):
        await _call(guarded)

    assert inner.call_count == 0  # refused before ever calling the inner provider


async def test_a_ledger_row_from_yesterday_does_not_count_against_todays_cap(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    llm.start_cost_guarded_task()
    async with session_factory() as db:
        db.add(
            LLMSpendLedger(
                provider="fake",
                model="x",
                tokens_in=1,
                tokens_out=1,
                estimated_cost_usd=5.0,
                created_at=datetime.now(UTC) - timedelta(days=1),
            )
        )
        await db.commit()

    inner = _FakeInnerProvider()
    guarded = llm.SpendGuardedProvider(inner, _settings(daily_spend_cap_usd=5.0))

    result = await _call(guarded)

    assert result == {"ok": True}
    assert inner.call_count == 1


async def test_a_successful_call_writes_a_ledger_row_with_the_real_token_counts_and_cost(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    llm.start_cost_guarded_task()
    inner = _FakeInnerProvider(tokens_in=1000, tokens_out=500)
    guarded = llm.SpendGuardedProvider(inner, _settings())

    await _call(guarded)

    async with session_factory() as db:
        row = (await db.execute(select(LLMSpendLedger))).scalar_one()

    assert row.tokens_in == 1000
    assert row.tokens_out == 500
    # claude-haiku-4-5-20251001: $0.001/1k in, $0.005/1k out (see llm._MODEL_PRICING)
    assert row.estimated_cost_usd == pytest.approx(1000 / 1000 * 0.001 + 500 / 1000 * 0.005)


async def test_a_refused_call_is_never_ledgered(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    llm.start_cost_guarded_task()
    inner = _FakeInnerProvider()
    guarded = llm.SpendGuardedProvider(inner, _settings(daily_spend_cap_usd=0.0))

    with pytest.raises(llm.LLMError):
        await _call(guarded)

    async with session_factory() as db:
        rows = (await db.execute(select(LLMSpendLedger))).scalars().all()
    assert rows == []
