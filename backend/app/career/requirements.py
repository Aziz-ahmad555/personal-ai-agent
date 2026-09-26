"""LLM-assisted extraction of a posting's *requirements*, for match scoring.

Same evidence discipline as Phase 3's claim extraction: the model may only report a
requirement it can back with a verbatim quote from the posting, and plain code then
re-checks that the quote really appears in the description (verify_citation_excerpt). A
requirement whose quote can't be found is dropped, never scored — it's the guardrail
against the model inventing "requires 5 years of Kubernetes" that the posting never said.

The LLM only *reads* here. Everything that turns requirements into a number lives in
app.career.matching, in plain code.
"""

from dataclasses import asdict, dataclass, field
from typing import Any

from app.research.llm import LLMProvider, wrap_untrusted
from app.research.verify import verify_citation_excerpt

EDUCATION_LEVELS = ("high_school", "associate", "bachelor", "master", "doctorate")

SYSTEM_PROMPT = """You extract the requirements a job posting states, for a personal
job-search agent that will compare them to a candidate's real profile. Rules:
- Record a requirement only if the posting explicitly states it. Never infer, generalize,
  or add skills that are merely typical for the role.
- Every requirement needs a `quote`: an exact, contiguous excerpt copied verbatim from the
  posting that states it. Do not paraphrase the quote.
- required_skills are things the posting says are required/must-have/necessary. Anything
  described as preferred, a plus, nice-to-have, or bonus goes in preferred_skills instead.
  If the posting doesn't say whether a skill is required or preferred, treat it as required
  only when it sits in a requirements/qualifications list; otherwise omit it.
- Skill `name` is a short canonical name (e.g. "Python", "PyTorch"), not a sentence.
- Omit min_years_experience, education, and industry entirely unless explicitly stated."""

SCHEMA_NAME = "record_job_requirements"
SCHEMA_DESCRIPTION = "Record the requirements a job posting explicitly states, each with a quote."

_SKILL_ITEM = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Short canonical skill name."},
        "quote": {"type": "string", "description": "Verbatim excerpt from the posting."},
    },
    "required": ["name", "quote"],
}

REQUIREMENTS_SCHEMA = {
    "type": "object",
    "properties": {
        "required_skills": {"type": "array", "items": _SKILL_ITEM},
        "preferred_skills": {"type": "array", "items": _SKILL_ITEM},
        "min_years_experience": {
            "type": "object",
            "description": "Years of experience the posting requires. Omit if not stated.",
            "properties": {
                "years": {"type": "integer"},
                "quote": {"type": "string", "description": "Verbatim excerpt."},
            },
            "required": ["years", "quote"],
        },
        "education": {
            "type": "object",
            "description": "Minimum education the posting requires. Omit if not stated.",
            "properties": {
                "level": {"type": "string", "enum": list(EDUCATION_LEVELS)},
                "quote": {"type": "string", "description": "Verbatim excerpt."},
            },
            "required": ["level", "quote"],
        },
        "industry": {
            "type": "object",
            "description": "The industry/sector the posting says the employer is in. "
            "Omit if not stated.",
            "properties": {
                "name": {"type": "string"},
                "quote": {"type": "string", "description": "Verbatim excerpt."},
            },
            "required": ["name", "quote"],
        },
    },
    "required": ["required_skills", "preferred_skills"],
}

DEAL_BREAKER_SYSTEM_PROMPT = """You check a job posting against a candidate's stated
deal-breakers. Report a deal-breaker only if the posting clearly and explicitly triggers it,
and give the exact verbatim excerpt from the posting that shows it. If a deal-breaker is
merely possible, uncertain, or not addressed by the posting, do not report it."""

DEAL_BREAKER_SCHEMA_NAME = "record_deal_breaker_hits"
DEAL_BREAKER_SCHEMA_DESCRIPTION = "Record which stated deal-breakers the posting clearly triggers."

DEAL_BREAKER_SCHEMA = {
    "type": "object",
    "properties": {
        "hits": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "deal_breaker": {
                        "type": "string",
                        "description": "The candidate's deal-breaker, as they wrote it.",
                    },
                    "quote": {"type": "string", "description": "Verbatim excerpt."},
                },
                "required": ["deal_breaker", "quote"],
            },
        }
    },
    "required": ["hits"],
}


@dataclass
class QuotedSkill:
    name: str
    quote: str


@dataclass
class JobRequirements:
    required_skills: list[QuotedSkill] = field(default_factory=list)
    preferred_skills: list[QuotedSkill] = field(default_factory=list)
    min_years_experience: int | None = None
    min_years_quote: str | None = None
    education_level: str | None = None
    education_quote: str | None = None
    industry: str | None = None
    industry_quote: str | None = None
    # How many items the model returned whose quote wasn't found in the posting and were
    # therefore dropped — surfaced so a heavily-hallucinating extraction is visible.
    dropped_unverified: int = 0

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DealBreakerHit:
    deal_breaker: str
    quote: str


def _verified_skills(raw: Any, description: str, counter: list[int]) -> list[QuotedSkill]:
    skills: list[QuotedSkill] = []
    seen: set[str] = set()
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        quote = str(item.get("quote") or "").strip()
        if not name or not verify_citation_excerpt(quote, description):
            counter[0] += 1
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        skills.append(QuotedSkill(name=name, quote=quote))
    return skills


async def extract_requirements(provider: LLMProvider, *, description: str) -> JobRequirements:
    payload = await provider.generate_structured(
        system=SYSTEM_PROMPT,
        user_message=f"Job posting text:\n\n{wrap_untrusted('job_posting', description)}",
        schema_name=SCHEMA_NAME,
        schema_description=SCHEMA_DESCRIPTION,
        json_schema=REQUIREMENTS_SCHEMA,
        max_tokens=2048,
    )

    dropped = [0]
    result = JobRequirements(
        required_skills=_verified_skills(payload.get("required_skills"), description, dropped),
        preferred_skills=_verified_skills(payload.get("preferred_skills"), description, dropped),
    )
    # A skill listed as both required and preferred is required — don't double count it.
    required_keys = {s.name.lower() for s in result.required_skills}
    result.preferred_skills = [
        s for s in result.preferred_skills if s.name.lower() not in required_keys
    ]

    years = payload.get("min_years_experience")
    if isinstance(years, dict):
        quote = str(years.get("quote") or "").strip()
        value = years.get("years")
        if isinstance(value, int) and value >= 0 and verify_citation_excerpt(quote, description):
            result.min_years_experience = value
            result.min_years_quote = quote
        else:
            dropped[0] += 1

    education = payload.get("education")
    if isinstance(education, dict):
        quote = str(education.get("quote") or "").strip()
        level = education.get("level")
        if level in EDUCATION_LEVELS and verify_citation_excerpt(quote, description):
            result.education_level = level
            result.education_quote = quote
        else:
            dropped[0] += 1

    industry = payload.get("industry")
    if isinstance(industry, dict):
        quote = str(industry.get("quote") or "").strip()
        name = str(industry.get("name") or "").strip()
        if name and verify_citation_excerpt(quote, description):
            result.industry = name
            result.industry_quote = quote
        else:
            dropped[0] += 1

    result.dropped_unverified = dropped[0]
    return result


async def check_deal_breakers(
    provider: LLMProvider, *, deal_breakers: str, description: str
) -> list[DealBreakerHit]:
    payload = await provider.generate_structured(
        system=DEAL_BREAKER_SYSTEM_PROMPT,
        user_message=(
            f"Candidate's deal-breakers:\n{deal_breakers}\n\nJob posting text:\n\n"
            f"{wrap_untrusted('job_posting', description)}"
        ),
        schema_name=DEAL_BREAKER_SCHEMA_NAME,
        schema_description=DEAL_BREAKER_SCHEMA_DESCRIPTION,
        json_schema=DEAL_BREAKER_SCHEMA,
        max_tokens=1024,
    )
    hits: list[DealBreakerHit] = []
    for item in payload.get("hits") or []:
        if not isinstance(item, dict):
            continue
        quote = str(item.get("quote") or "").strip()
        label = str(item.get("deal_breaker") or "").strip()
        # A "hit" with no verifiable quote is exactly the kind of claim that must never be
        # shown to the user as fact.
        if label and verify_citation_excerpt(quote, description):
            hits.append(DealBreakerHit(deal_breaker=label, quote=quote))
    return hits
