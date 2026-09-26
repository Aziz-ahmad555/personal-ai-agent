"""Report drafting: the LLM sees only already-persisted, already-scored claims (never raw
source text) and must cite each sentence with an inline [claim_id] marker. Plain code then
drops any *sentence* whose marker doesn't match a real claim id before the report is stored
— not just the marker itself, since "The role pays $200k [bogus]" stripped down to "The role
pays $200k" is exactly as unattributed an assertion as one with no citation at all. The model
cannot introduce an unattributed fact that survives into the final summary this way.
Provider-agnostic, like app.research.extraction.

A sentence with no marker at all is left untouched — that's a separate, harder problem (the
model asserting something with no citation whatsoever, rather than a citation that fails to
resolve) that this module doesn't attempt to solve."""

import re
from dataclasses import dataclass

from app.logging import get_logger
from app.research.llm import LLMProvider

logger = get_logger(__name__)

SYSTEM_PROMPT = """You are drafting a short research report for a personal job-search agent.
You will be given a research question and a list of already-verified claims, each with a
short id, its text, its status (corroborated / single_source / contradicted / unverified),
and its confidence score (0-100).

Write a concise synthesized answer (a few sentences to a short paragraph). Every sentence
that states a fact MUST end with the id of the claim it's based on in square brackets, e.g.
"The role requires 5 years of PyTorch experience [c1]." Do not state anything that isn't
backed by one of the given claim ids — if the claims don't cover part of the question, leave
it out of the summary and put it in `uncertainties` instead. Never mention a claim id that
was not given to you."""

SCHEMA_NAME = "write_report"
SCHEMA_DESCRIPTION = "Write the synthesized research report."

REPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "string",
            "description": (
                "The synthesized answer, with every factual sentence ending in a [claim_id] marker."
            ),
        },
        "uncertainties": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Parts of the research question the claims don't cover.",
        },
    },
    "required": ["summary", "uncertainties"],
}

_MARKER_RE = re.compile(r"\[([a-zA-Z0-9_-]+)\]")
# Splits on the whitespace following a sentence-ending punctuation mark, keeping that
# punctuation attached to the sentence before it — good enough for the short, schema-
# constrained summaries this module produces (not a general-purpose sentence tokenizer).
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


@dataclass
class ClaimForReport:
    id: str
    claim_text: str
    status: str
    confidence_score: int


@dataclass
class ReportDraft:
    summary: str
    uncertainties: list[str]
    referenced_claim_ids: list[str]


def _build_user_message(query_text: str, purpose: str | None, claims: list[ClaimForReport]) -> str:
    parts = [f"Research question: {query_text}"]
    if purpose:
        parts.append(f"Context/purpose: {purpose}")
    parts.append("\nClaims:")
    for claim in claims:
        parts.append(
            f"- id={claim.id} status={claim.status} confidence={claim.confidence_score}: "
            f"{claim.claim_text}"
        )
    return "\n".join(parts)


def _drop_unsupported_sentences(summary: str, known_ids: set[str]) -> tuple[str, list[str]]:
    """Drops any *sentence* containing a [marker] that isn't a known claim id — not just the
    bracket — so an invented citation can never leave its assertion behind, stripped of the
    one thing that would have revealed it as unsupported. Returns the cleaned summary and the
    ids actually referenced by the sentences that survived."""
    referenced: list[str] = []
    kept: list[str] = []

    for sentence in _SENTENCE_SPLIT_RE.split(summary):
        if not sentence.strip():
            continue
        markers = _MARKER_RE.findall(sentence)
        if markers and not all(marker in known_ids for marker in markers):
            continue  # at least one citation doesn't resolve — drop the whole sentence
        referenced.extend(marker for marker in markers if marker in known_ids)
        kept.append(sentence)

    cleaned = re.sub(r"\s+", " ", " ".join(kept)).strip()
    return cleaned, referenced


async def draft_report(
    provider: LLMProvider,
    *,
    query_text: str,
    purpose: str | None,
    claims: list[ClaimForReport],
) -> ReportDraft:
    if not claims:
        return ReportDraft(
            summary="No verified claims were found for this query.",
            uncertainties=["No sources could be verified well enough to support any claim."],
            referenced_claim_ids=[],
        )

    payload = await provider.generate_structured(
        system=SYSTEM_PROMPT,
        user_message=_build_user_message(query_text, purpose, claims),
        schema_name=SCHEMA_NAME,
        schema_description=SCHEMA_DESCRIPTION,
        json_schema=REPORT_SCHEMA,
        # See the comment on the equivalent call in extraction.py — some providers spend
        # part of this budget on hidden reasoning tokens before the visible JSON.
        max_tokens=3072,
    )

    known_ids = {claim.id for claim in claims}
    cleaned_summary, referenced = _drop_unsupported_sentences(payload.get("summary", ""), known_ids)
    return ReportDraft(
        summary=cleaned_summary or "The available claims did not yield a clear summary.",
        uncertainties=payload.get("uncertainties", []),
        referenced_claim_ids=referenced,
    )
