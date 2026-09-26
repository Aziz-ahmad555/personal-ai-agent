"""Research Engine eval bucket.

Replay mode: runs the real app.research.report.draft_report against a FakeLLM (canned raw
model output) for each evals/datasets/research_eval.json pipeline example, and checks the
code's own marker-stripping behavior deterministically — including a concrete, reproducible
demonstration of a real gap: draft_report only strips a citation marker that doesn't match a
real claim id, it does not remove the (possibly unsupported) sentence around it. This is a
code-correctness check, not a language-quality judgment, so it needs no judge and no live call.

Live mode additionally: runs the LLM-judge (evals/judge.py) against the same hand-labeled
research_judge_gold.json examples reused as both the scoring set and the calibration set (its
labels were assigned once, by a human, before ever running the judge against them), and prints
the judge's agreement rate with those labels every run — a drifting judge is visible, not
silently trusted. Also runs one real baseline comparison: the same query sent directly to the
raw model with no retrieval/citation pipeline, to show what the pipeline's verification layer
is actually protecting against.
"""

import json
from dataclasses import dataclass
from typing import Any

from app.research.llm import LLMProvider, record_llm_calls
from app.research.report import ClaimForReport, draft_report

from evals.config import DATASETS_DIR
from evals.report import BucketReport, TaskResult


class _FakeLLM:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload
        self.called = False

    async def generate_structured(self, **kwargs: Any) -> dict[str, Any]:
        self.called = True
        return self._payload


def _load_pipeline_examples() -> list[dict[str, Any]]:
    data = json.loads((DATASETS_DIR / "research_eval.json").read_text())
    return list(data["pipeline_examples"])


def _load_judge_gold() -> list[dict[str, Any]]:
    data = json.loads((DATASETS_DIR / "research_judge_gold.json").read_text())
    return list(data["examples"])


async def run_replay() -> BucketReport:
    tasks: list[TaskResult] = []
    for ex in _load_pipeline_examples():
        claims = [
            ClaimForReport(
                id=c["id"], claim_text=c["text"], status=c["status"], confidence_score=c["confidence_score"]
            )
            for c in ex["claims"]
        ]
        fake = _FakeLLM({"summary": ex["fake_llm_summary"], "uncertainties": ex["fake_llm_uncertainties"]})

        draft = await draft_report(fake, query_text=ex["query_text"], purpose=None, claims=claims)

        ids_match = sorted(draft.referenced_claim_ids) == sorted(ex["expected_referenced_ids"])
        residue_expected = ex["expected_marker_stripping_leaves_unsupported_residue"]
        residue_substring: str | None = ex.get("unsupported_residue_substring")
        residue_present = residue_substring is not None and residue_substring in draft.summary
        residue_matches_expectation = residue_present == residue_expected

        passed = ids_match and residue_matches_expectation
        tasks.append(
            TaskResult(
                task_id=f"pipeline:{ex['id']}",
                passed=passed,
                score=1.0 if passed else 0.0,
                detail=(
                    f"{ex['note']} | referenced_ids={draft.referenced_claim_ids} "
                    f"(expected {ex['expected_referenced_ids']}) | "
                    f"unsupported residue present={residue_present} (expected {residue_expected})"
                ),
            )
        )
    return BucketReport(name="research_engine", tasks=tasks)


@dataclass(frozen=True)
class LiveResearchResult:
    scoring_tasks: list[TaskResult]
    calibration_agreement_rate: float
    calibration_disagreements: list[str]


async def run_live_supplementary(provider: LLMProvider) -> LiveResearchResult:
    from evals.judge import judge_calibration, judge_report

    gold = _load_judge_gold()
    scoring_tasks: list[TaskResult] = []
    for example in gold:
        records = record_llm_calls()
        verdict = await judge_report(
            provider,
            query_text=example["query_text"],
            claims=example["claims"],
            summary=example["summary"],
        )
        passed = (
            verdict.faithful == example["expected_faithful"]
            and verdict.relevant == example["expected_relevant"]
        )
        task = TaskResult(
            task_id=f"judge_scoring:{example['id']}",
            passed=passed,
            score=1.0 if passed else 0.0,
            detail=(
                f"judge said faithful={verdict.faithful} relevant={verdict.relevant} ({verdict.reason})"
            ),
        )
        task.llm_calls = records
        scoring_tasks.append(task)

    calibration = await judge_calibration(provider, gold)
    return LiveResearchResult(
        scoring_tasks=scoring_tasks,
        calibration_agreement_rate=calibration.agreement_rate,
        calibration_disagreements=calibration.disagreements,
    )
