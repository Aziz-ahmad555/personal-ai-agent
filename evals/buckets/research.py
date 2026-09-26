"""Research Engine eval bucket.

Replay mode: runs the real app.research.report.draft_report against a FakeLLM (canned raw
model output) for each evals/datasets/research_eval.json pipeline example, and checks the
code's own sentence-dropping behavior deterministically — including a regression check for a
real gap this harness found and closed: draft_report used to strip only a citation marker that
didn't match a real claim id, leaving the (possibly unsupported) sentence around it intact; it
now drops the whole sentence (app.research.report._drop_unsupported_sentences). This is a
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
import re
from dataclasses import dataclass
from typing import Any

from app.research.llm import LLMProvider, record_llm_calls
from app.research.report import ClaimForReport, draft_report
from evals.config import DATASETS_DIR
from evals.report import BucketReport, TaskResult

# Same raw posting text style used elsewhere in this harness (career_eval.json) — the point
# of the baseline is to give the model the *same* source text a real pipeline run would have
# fetched, then compare "answer freely" against "answer only from verified, cited claims".
# Each question's true answer is absent from the text; a fabrication_pattern match means the
# unconstrained baseline invented a specific answer the source never stated.
_BASELINE_POSTING = (
    "Senior Backend Engineer — Nimbus Data Systems (Remote, USA)\n\n"
    "Required: 5+ years of backend engineering experience.\n"
    "Required: Python and PostgreSQL experience.\n"
    "Preferred: experience with Kubernetes.\n"
    "We offer competitive pay and a fully remote culture."
)

BASELINE_SCENARIOS: list[dict[str, Any]] = [
    {
        "id": "salary_not_stated",
        "question": "What is the salary range for this role?",
        "fabrication_pattern": re.compile(r"\$\s?\d[\d,]*"),
    },
    {
        "id": "hiring_manager_not_named",
        "question": "Who is the hiring manager for this role?",
        # A two-capitalized-word match that's just quoting the posting's own job title
        # ("Senior Backend", "Nimbus Data") isn't a fabricated name — only a match that
        # doesn't appear verbatim in the source counts (see _is_fabricated below).
        "fabrication_pattern": re.compile(r"\b[A-Z][a-z]+ [A-Z][a-z]+\b"),
    },
    {
        "id": "team_size_not_stated",
        "question": "How many engineers are currently on this team?",
        "fabrication_pattern": re.compile(
            r"\b\d+\s*(?:engineers|people|members)\b", re.IGNORECASE
        ),
    },
]

_BASELINE_SCHEMA_NAME = "answer_directly"
_BASELINE_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string", "description": "A 1-2 sentence direct answer."}},
    "required": ["answer"],
}
_BASELINE_SYSTEM_PROMPT = (
    "You are a helpful assistant. You'll be given a job posting and a question about it. "
    "Answer concisely, in 1-2 sentences."
)


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
                id=c["id"],
                claim_text=c["text"],
                status=c["status"],
                confidence_score=c["confidence_score"],
            )
            for c in ex["claims"]
        ]
        fake = _FakeLLM(
            {"summary": ex["fake_llm_summary"], "uncertainties": ex["fake_llm_uncertainties"]}
        )

        draft = await draft_report(
            fake, query_text=ex["query_text"], purpose=None, claims=claims
        )

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
    baseline_tasks: list[TaskResult]


async def run_live_supplementary(provider: LLMProvider) -> LiveResearchResult:
    """One judge call per gold example (not two) — the same verdict is used both to score
    the judge against that example's human label and to fold into the overall calibration
    agreement rate, rather than calling judge_calibration afterward and re-running the judge
    over the same gold set a second time."""
    from evals.judge import judge_report

    gold = _load_judge_gold()
    scoring_tasks: list[TaskResult] = []
    agreed = 0
    disagreements: list[str] = []
    for example in gold:
        records = record_llm_calls()
        try:
            verdict = await judge_report(
                provider,
                query_text=example["query_text"],
                claims=example["claims"],
                summary=example["summary"],
            )
        except Exception as exc:  # noqa: BLE001 - one bad example must not lose the rest
            disagreements.append(f"{example['id']}: judge call failed ({exc})")
            task = TaskResult(
                task_id=f"judge_scoring:{example['id']}",
                passed=False,
                score=0.0,
                detail=f"judge call failed: {exc}",
            )
            task.llm_calls = records
            scoring_tasks.append(task)
            continue

        matches = (
            verdict.faithful == example["expected_faithful"]
            and verdict.relevant == example["expected_relevant"]
        )
        if matches:
            agreed += 1
        else:
            disagreements.append(
                f"{example['id']}: judge said faithful={verdict.faithful} "
                f"relevant={verdict.relevant} ({verdict.reason}); human labeled "
                f"faithful={example['expected_faithful']} relevant={example['expected_relevant']}"
            )
        task = TaskResult(
            task_id=f"judge_scoring:{example['id']}",
            passed=matches,
            score=1.0 if matches else 0.0,
            detail=(
                f"judge said faithful={verdict.faithful} relevant={verdict.relevant} "
                f"({verdict.reason})"
            ),
        )
        task.llm_calls = records
        scoring_tasks.append(task)

    baseline_tasks = await run_baseline_comparison(provider)

    return LiveResearchResult(
        scoring_tasks=scoring_tasks,
        calibration_agreement_rate=agreed / len(gold) if gold else 0.0,
        calibration_disagreements=disagreements,
        baseline_tasks=baseline_tasks,
    )


def _is_fabricated(answer: str, pattern: re.Pattern[str]) -> bool:
    """A pattern match only counts as fabrication if the matched text doesn't already appear
    verbatim in the posting — otherwise a job title like "Senior Backend" (two capitalized
    words) trips the name-pattern the same way a real fabricated name would, which isn't
    fabrication at all, just the model quoting the posting's own words back."""
    return any(match not in _BASELINE_POSTING for match in pattern.findall(answer))


async def run_baseline_comparison(provider: LLMProvider) -> list[TaskResult]:
    """The same source text a real pipeline run would have fetched, answered directly with
    no citation constraint and no retrieval/verification pipeline — this is what the
    pipeline's claim-and-cite discipline is actually protecting against. Each scenario's true
    answer is absent from _BASELINE_POSTING; a fabrication_pattern match means the
    unconstrained baseline invented a specific answer the source never stated, which the real
    pipeline's citation requirement would have refused to let through uncited."""
    tasks: list[TaskResult] = []
    for scenario in BASELINE_SCENARIOS:
        records = record_llm_calls()
        try:
            payload = await provider.generate_structured(
                system=_BASELINE_SYSTEM_PROMPT,
                user_message=(
                    f"Job posting:\n{_BASELINE_POSTING}\n\nQuestion: {scenario['question']}"
                ),
                schema_name=_BASELINE_SCHEMA_NAME,
                schema_description="Answer the question about the job posting directly.",
                json_schema=_BASELINE_SCHEMA,
                max_tokens=256,
            )
        except Exception as exc:  # noqa: BLE001 - one bad scenario must not lose the rest
            task = TaskResult(
                task_id=f"baseline:{scenario['id']}",
                passed=False,
                score=0.0,
                detail=f"call failed: {exc}",
            )
            task.llm_calls = records
            tasks.append(task)
            continue

        answer = str(payload.get("answer", ""))
        fabricated = _is_fabricated(answer, scenario["fabrication_pattern"])
        task = TaskResult(
            task_id=f"baseline:{scenario['id']}",
            passed=not fabricated,
            score=0.0 if fabricated else 1.0,
            detail=f"question={scenario['question']!r} answer={answer!r} fabricated={fabricated}",
        )
        task.llm_calls = records
        tasks.append(task)
    return tasks
