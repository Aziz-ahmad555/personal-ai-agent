"""LLM-assisted structured extraction. The model sees only labeled, tier-classified source
excerpts and must return claims as structured JSON (never free prose) — every claim
requires at least one citation carrying a verbatim quote and the source id it came from.
This module does NOT decide whether a citation is trustworthy; app.research.verify's
verify_citation_excerpt re-checks every excerpt against the actual stored source content
afterward, and anything that fails that check is dropped by the pipeline, not by the
model's own say-so. Provider-agnostic: works with whatever app.research.llm.LLMProvider
is configured."""

from dataclasses import dataclass
from typing import Any

from app.logging import get_logger
from app.research.llm import LLMProvider, wrap_untrusted

logger = get_logger(__name__)

SYSTEM_PROMPT = """You are a research extraction assistant for a personal job-search agent.
You will be given a research question and a set of labeled source excerpts, each with a
short id, its domain, and its trust tier (official > government > docs > reputable_secondary
> forum_anecdotal > unknown).

Extract only atomic factual claims that are explicitly stated in the provided excerpts.
Never use outside knowledge, never infer beyond what the text says, never invent a number,
date, or quote that is not present verbatim in the given text.

For every claim you record, you MUST attach at least one citation: the exact source id and
an excerpt copied character-for-character from that source's text (do not paraphrase the
excerpt). If multiple sources support the same fact, attach one citation per supporting
source on the same claim rather than creating duplicate claims. If a source contradicts
another, record a citation with stance "contradicts" pointing at the contradicting source.

If the provided sources do not answer some part of the research question, do not guess —
list that gap in `uncertainties` instead of fabricating a claim."""

SCHEMA_NAME = "record_claims"
SCHEMA_DESCRIPTION = "Record atomic factual claims extracted from the provided sources."

CLAIMS_SCHEMA = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim_text": {
                        "type": "string",
                        "description": "A single atomic factual statement.",
                    },
                    "claim_type": {
                        "type": "string",
                        "description": (
                            "Short free-form category, e.g. 'salary_range', 'employer_verified'."
                        ),
                    },
                    "value": {
                        "type": "object",
                        "description": (
                            "Structured form of the claim when the fact is naturally structured, "
                            'e.g. {"min": 120000, "max": 150000, "currency": "USD"} for a '
                            "salary range. Omit for claims that are only prose."
                        ),
                    },
                    "citations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "source_id": {"type": "string"},
                                "excerpt": {
                                    "type": "string",
                                    "description": (
                                        "Verbatim quote copied exactly from the source text."
                                    ),
                                },
                                "stance": {
                                    "type": "string",
                                    "enum": ["supports", "contradicts", "context_only"],
                                },
                            },
                            "required": ["source_id", "excerpt", "stance"],
                        },
                    },
                },
                "required": ["claim_text", "citations"],
            },
        },
        "uncertainties": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Parts of the research question the given sources did not answer.",
        },
    },
    "required": ["claims", "uncertainties"],
}


@dataclass
class ExtractedCitation:
    source_id: str
    excerpt: str
    stance: str


@dataclass
class ExtractedClaim:
    claim_text: str
    claim_type: str | None
    value: dict[str, Any] | None
    citations: list[ExtractedCitation]


@dataclass
class ExtractionResult:
    claims: list[ExtractedClaim]
    uncertainties: list[str]


@dataclass
class SourceExcerpt:
    id: str
    domain: str
    tier: str
    title: str | None
    content: str


def _build_user_message(query_text: str, purpose: str | None, sources: list[SourceExcerpt]) -> str:
    parts = [f"Research question: {query_text}"]
    if purpose:
        parts.append(f"Context/purpose: {purpose}")
    parts.append("\nSources:")
    for source in sources:
        header = (
            f"source_id: {source.id}\ndomain: {source.domain}\ntier: {source.tier}\n"
            f"title: {source.title or '(untitled)'}"
        )
        parts.append(f"\n---\n{header}\n{wrap_untrusted('source_excerpt', source.content)}")
    return "\n".join(parts)


async def extract_claims(
    provider: LLMProvider,
    *,
    query_text: str,
    purpose: str | None,
    sources: list[SourceExcerpt],
) -> ExtractionResult:
    if not sources:
        return ExtractionResult(
            claims=[], uncertainties=["No verified sources were collected for this query."]
        )

    payload = await provider.generate_structured(
        system=SYSTEM_PROMPT,
        user_message=_build_user_message(query_text, purpose, sources),
        schema_name=SCHEMA_NAME,
        schema_description=SCHEMA_DESCRIPTION,
        json_schema=CLAIMS_SCHEMA,
        # Generous relative to expected output size: some providers (e.g. Gemini's
        # reasoning models) spend part of this budget on internal reasoning tokens before
        # the visible JSON, so a tight budget can truncate the response before the schema
        # is satisfied even when the actual claims text would be short.
        max_tokens=8192,
    )

    claims = [
        ExtractedClaim(
            claim_text=c["claim_text"],
            claim_type=c.get("claim_type"),
            value=c.get("value"),
            citations=[
                ExtractedCitation(
                    source_id=cit["source_id"], excerpt=cit["excerpt"], stance=cit["stance"]
                )
                for cit in c.get("citations", [])
            ],
        )
        for c in payload.get("claims", [])
    ]
    return ExtractionResult(claims=claims, uncertainties=payload.get("uncertainties", []))
