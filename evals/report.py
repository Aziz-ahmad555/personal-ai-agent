"""Aggregation and output for eval runs: turns each bucket's individual task results into a
console table and a JSON file, and rolls up latency/cost/token totals from every LLM call any
task made along the way (via app.research.llm.record_llm_calls)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from app.research.llm import LLMCallRecord

from evals.config import REPORTS_DIR, estimate_cost_usd


@dataclass
class TaskResult:
    task_id: str
    passed: bool | None  # None = not scored pass/fail (e.g. a continuous metric only)
    score: float | None  # 0-1, when the task has a continuous metric (hit rate, judge score)
    detail: str
    llm_calls: list[LLMCallRecord] = field(default_factory=list)


@dataclass
class BucketReport:
    name: str
    applicable: bool = True
    note: str | None = None  # set when applicable=False, explaining why
    tasks: list[TaskResult] = field(default_factory=list)

    @property
    def scored_tasks(self) -> list[TaskResult]:
        return [t for t in self.tasks if t.passed is not None]

    @property
    def pass_count(self) -> int:
        return sum(1 for t in self.scored_tasks if t.passed)

    @property
    def total_scored(self) -> int:
        return len(self.scored_tasks)

    @property
    def pass_rate(self) -> float | None:
        if self.total_scored == 0:
            return None
        return self.pass_count / self.total_scored

    @property
    def mean_score(self) -> float | None:
        scored = [t.score for t in self.tasks if t.score is not None]
        if not scored:
            return None
        return sum(scored) / len(scored)


@dataclass
class EvalReport:
    mode: Literal["replay", "live"]
    buckets: list[BucketReport] = field(default_factory=list)
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None

    def all_llm_calls(self) -> list[LLMCallRecord]:
        return [call for bucket in self.buckets for task in bucket.tasks for call in task.llm_calls]

    def totals(self) -> dict[str, Any]:
        calls = self.all_llm_calls()
        tokens_in = sum(c.tokens_in or 0 for c in calls)
        tokens_out = sum(c.tokens_out or 0 for c in calls)
        latency_ms = sum(c.latency_ms for c in calls)
        cost = sum(
            estimate_cost_usd(c.model, c.tokens_in, c.tokens_out) or 0
            for c in calls
            if estimate_cost_usd(c.model, c.tokens_in, c.tokens_out) is not None
        )
        cost_is_partial = any(
            estimate_cost_usd(c.model, c.tokens_in, c.tokens_out) is None for c in calls
        )
        return {
            "llm_calls": len(calls),
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "total_latency_ms": round(latency_ms, 1),
            "estimated_cost_usd": round(cost, 4),
            "cost_estimate_incomplete": cost_is_partial,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "totals": self.totals(),
            "buckets": [
                {
                    "name": b.name,
                    "applicable": b.applicable,
                    "note": b.note,
                    "pass_count": b.pass_count,
                    "total_scored": b.total_scored,
                    "pass_rate": b.pass_rate,
                    "mean_score": b.mean_score,
                    "tasks": [
                        {
                            "task_id": t.task_id,
                            "passed": t.passed,
                            "score": t.score,
                            "detail": t.detail,
                            "llm_calls": len(t.llm_calls),
                        }
                        for t in b.tasks
                    ],
                }
                for b in self.buckets
            ],
        }

    def save_json(self) -> str:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        stamp = self.started_at.strftime("%Y%m%dT%H%M%SZ")
        path = REPORTS_DIR / f"eval_run_{stamp}.json"
        path.write_text(json.dumps(self.to_dict(), indent=2))
        return str(path)

    def print_console(self) -> None:
        print(f"\n=== Eval run ({self.mode} mode) ===\n")
        for b in self.buckets:
            if not b.applicable:
                print(f"[{b.name}] SKIPPED — {b.note}")
                continue
            rate = f"{b.pass_rate:.0%}" if b.pass_rate is not None else "n/a"
            mean = f"{b.mean_score:.2f}" if b.mean_score is not None else "n/a"
            print(
                f"[{b.name}] pass {b.pass_count}/{b.total_scored} ({rate})"
                f"{f', mean score {mean}' if b.mean_score is not None else ''}"
            )
            for t in b.tasks:
                if t.passed is False:
                    print(f"    FAIL {t.task_id}: {t.detail}")
        totals = self.totals()
        print("\n--- Cost / latency / tokens (estimated) ---")
        print(
            f"{totals['llm_calls']} real LLM calls, "
            f"{totals['tokens_in']} in / {totals['tokens_out']} out tokens, "
            f"{totals['total_latency_ms']:.0f}ms total latency, "
            f"~${totals['estimated_cost_usd']:.4f}"
            f"{' (incomplete — some calls used a model with no price entry)' if totals['cost_estimate_incomplete'] else ''}"
        )
