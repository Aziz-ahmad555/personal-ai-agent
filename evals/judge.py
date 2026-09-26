"""The LLM-judge: scores a Research Engine report's summary for faithfulness (does it only
assert what the given claims actually support) and relevance (does it answer the question).

This exists because citation *existence* alone doesn't guarantee narrative faithfulness. A
real, specific version of that gap was found while building this harness — draft_report used
to strip only an [id] marker that didn't match a real claim, leaving the surrounding sentence's
unsupported assertion intact (e.g. "The role pays $200k [bogus]" -> "The role pays $200k") —
and is now fixed at the code level (app.research.report._drop_unsupported_sentences drops the
whole sentence). But a sentence with no citation marker at all, or one that subtly overstates
what its real citation actually says, isn't something more string-matching code can reliably
catch — that's what still needs a judge.

Calibration: judge_calibration() runs the judge against a small, hand-labeled gold set
(evals/datasets/research_judge_gold.json) and reports its agreement rate with those labels —
printed on every --live run, so a drifting judge is visible rather than silently trusted.
"""

from dataclasses import dataclass
from typing import Any

from app.research.llm import LLMProvider
from app.research.report import NO_CLAIMS_FALLBACK_SUMMARY

JUDGE_SYSTEM_PROMPT = """You are a strict fact-checking judge for a personal research
assistant. You will be given a research question, the exact claims (with ids) the assistant
was allowed to use, and the summary it produced. Judge two things:

- faithful: true only if EVERY factual assertion in the summary is directly supported by one
  of the given claims. A sentence with a citation marker that names a real claim id still
  counts as faithful only if the claim actually supports what the sentence says — a citation
  next to an unsupported assertion does not make it faithful. If the summary asserts anything
  the claims don't cover (a number, a name, a fact), faithful is false.
  Also false if the summary cites a claim while silently ignoring another given claim that
  directly contradicts it — e.g. citing "the careers page says fully remote" without
  mentioning a given claim that says the team was actually told to return to office. Citing a
  true claim while omitting a claim that contradicts it is still unfaithful: the reader is
  misled into thinking the cited claim is the whole picture. A summary that acknowledges the
  contradiction (e.g. "sources disagree here") is faithful.
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
    # The app's own deterministic fallback for zero claims (app.research.report.draft_report
    # short-circuits before ever calling a model) — scored faithful/relevant by construction,
    # never sent to the judge as if it were generated prose. Matches CLAUDE.md's "no LLM for
    # deterministic work": a hardcoded string doesn't need a model to grade it, and asking one
    # to only invites exactly the false-negative a strict "assertion needs a citation" rule
    # would produce here (an honest admission of absence isn't an uncited factual claim).
    if not claims and summary == NO_CLAIMS_FALLBACK_SUMMARY:
        return JudgeVerdict(
            faithful=True,
            relevant=True,
            reason=(
                "The app's built-in fallback for zero verified claims — scored by "
                "construction, not evaluated as generated prose."
            ),
        )

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
                f"{example['id']}: judge said faithful={verdict.faithful} "
                f"relevant={verdict.relevant} ({verdict.reason}); human labeled "
                f"faithful={example['expected_faithful']} relevant={example['expected_relevant']}"
            )
    return CalibrationResult(total=len(gold_examples), agreed=agreed, disagreements=disagreements)
