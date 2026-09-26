"""The LLM-judge: scores a Research Engine report's summary for faithfulness (does it only
assert what the given claims actually support) and relevance (does it answer the question).

This exists because of a real, specific gap in app.research.report.draft_report: the code only
strips an [id] marker that doesn't match a real claim — it does NOT remove the surrounding
sentence, so a sentence can survive with its fake citation stripped but its unsupported
assertion intact (e.g. "The role pays $200k [bogus]" -> "The role pays $200k"). Citation
*existence* is already deterministically guaranteed; narrative faithfulness of the resulting
free text is not, and that's what needs a judge rather than more code.

Calibration: judge_calibration() runs the judge against a small, hand-labeled gold set
(evals/datasets/research_judge_gold.json) and reports its agreement rate with those labels —
printed on every --live run, so a drifting judge is visible rather than silently trusted.
"""

from dataclasses import dataclass
from typing import Any

from app.research.llm import LLMProvider

JUDGE_SYSTEM_PROMPT = """You are a strict fact-checking judge for a personal research
assistant. You will be given a research question, the exact claims (with ids) the assistant
was allowed to use, and the summary it produced. Judge two things:

- faithful: true only if EVERY factual assertion in the summary is directly supported by one
  of the given claims. A sentence with a citation marker that names a real claim id still
  counts as faithful only if the claim actually supports what the sentence says — a citation
  next to an unsupported assertion does not make it faithful. If the summary asserts anything
  the claims don't cover (a number, a name, a fact), faithful is false.
- relevant: true only if the summary actually addresses the research question asked, not a
  related-but-different topic.

Be strict: when in doubt about whether a claim supports a specific assertion, judge it as not
faithful and say why in `reason`."""

JUDGE_SCHEMA_NAME = "judge_research_report"
JUDGE_SCHEMA_DESCRIPTION = "Judge a research report summary for faithfulness and relevance."

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "faithful": {"type": "boolean"},
        "relevant": {"type": "boolean"},
        "reason": {"type": "string", "description": "One or two sentences explaining the verdict."},
    },
    "required": ["faithful", "relevant", "reason"],
}


@dataclass(frozen=True)
class JudgeVerdict:
    faithful: bool
    relevant: bool
    reason: str


def _build_user_message(
    *, query_text: str, claims: list[dict[str, str]], summary: str
) -> str:
    claim_lines = "\n".join(f"- id={c['id']}: {c['text']}" for c in claims) or "(no claims given)"
    return (
        f"Research question: {query_text}\n\n"
        f"Claims the assistant was allowed to use:\n{claim_lines}\n\n"
        f"Summary produced:\n{summary}"
    )


async def judge_report(
    provider: LLMProvider, *, query_text: str, claims: list[dict[str, str]], summary: str
) -> JudgeVerdict:
    payload: dict[str, Any] = await provider.generate_structured(
        system=JUDGE_SYSTEM_PROMPT,
        user_message=_build_user_message(query_text=query_text, claims=claims, summary=summary),
        schema_name=JUDGE_SCHEMA_NAME,
        schema_description=JUDGE_SCHEMA_DESCRIPTION,
        json_schema=JUDGE_SCHEMA,
        max_tokens=512,
    )
    return JudgeVerdict(
        faithful=bool(payload.get("faithful")),
        relevant=bool(payload.get("relevant")),
        reason=str(payload.get("reason") or ""),
    )


@dataclass(frozen=True)
class CalibrationResult:
    total: int
    agreed: int
    disagreements: list[str]

    @property
    def agreement_rate(self) -> float:
        return self.agreed / self.total if self.total else 0.0


async def judge_calibration(
    provider: LLMProvider, gold_examples: list[dict[str, Any]]
) -> CalibrationResult:
    """Runs the judge against a hand-labeled gold set and reports agreement. Each gold example
    carries the human's own faithful/relevant labels (`expected_faithful`/`expected_relevant`)
    — set by a human reading the summary and claims directly, not derived from the judge."""
    agreed = 0
    disagreements: list[str] = []
    for example in gold_examples:
        verdict = await judge_report(
            provider,
            query_text=example["query_text"],
            claims=example["claims"],
            summary=example["summary"],
        )
        matches = (
            verdict.faithful == example["expected_faithful"]
            and verdict.relevant == example["expected_relevant"]
        )
        if matches:
            agreed += 1
        else:
            disagreements.append(
                f"{example['id']}: judge said faithful={verdict.faithful} relevant={verdict.relevant} "
                f"({verdict.reason}); human labeled faithful={example['expected_faithful']} "
                f"relevant={example['expected_relevant']}"
            )
    return CalibrationResult(total=len(gold_examples), agreed=agreed, disagreements=disagreements)
