"""The requirement extractor must never let an LLM-invented requirement reach scoring: every
item needs a quote that plain code can find in the posting."""

from app.career.requirements import check_deal_breakers, extract_requirements

DESCRIPTION = (
    "We need a Machine Learning Engineer. Requirements: 5+ years of experience, strong Python "
    "and PyTorch skills, and a Bachelor's degree. Nice to have: Kubernetes. We are a "
    "healthcare company. On-call weekends are required."
)


class _FakeLLM:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    async def generate_structured(self, **kwargs: object) -> dict:
        return self._payload


async def test_quoted_requirements_are_kept() -> None:
    llm = _FakeLLM(
        {
            "required_skills": [
                {"name": "Python", "quote": "strong Python and PyTorch skills"},
                {"name": "PyTorch", "quote": "strong Python and PyTorch skills"},
            ],
            "preferred_skills": [{"name": "Kubernetes", "quote": "Nice to have: Kubernetes"}],
            "min_years_experience": {"years": 5, "quote": "5+ years of experience"},
            "education": {"level": "bachelor", "quote": "a Bachelor's degree"},
            "industry": {"name": "Healthcare", "quote": "We are a healthcare company"},
        }
    )

    req = await extract_requirements(llm, description=DESCRIPTION)  # type: ignore[arg-type]

    assert [s.name for s in req.required_skills] == ["Python", "PyTorch"]
    assert [s.name for s in req.preferred_skills] == ["Kubernetes"]
    assert (req.min_years_experience, req.education_level, req.industry) == (
        5,
        "bachelor",
        "Healthcare",
    )
    assert req.dropped_unverified == 0


async def test_requirements_with_fabricated_quotes_are_dropped_and_counted() -> None:
    llm = _FakeLLM(
        {
            "required_skills": [
                {"name": "Python", "quote": "strong Python and PyTorch skills"},
                {"name": "Rust", "quote": "must know Rust inside out"},  # not in the posting
            ],
            "preferred_skills": [],
            "min_years_experience": {"years": 10, "quote": "10+ years of experience"},  # invented
            "education": {"level": "doctorate", "quote": "a PhD is required"},  # invented
        }
    )

    req = await extract_requirements(llm, description=DESCRIPTION)  # type: ignore[arg-type]

    assert [s.name for s in req.required_skills] == ["Python"]
    assert req.min_years_experience is None
    assert req.education_level is None
    assert req.dropped_unverified == 3


async def test_skill_listed_as_both_required_and_preferred_counts_once_as_required() -> None:
    llm = _FakeLLM(
        {
            "required_skills": [{"name": "Python", "quote": "strong Python and PyTorch skills"}],
            "preferred_skills": [
                {"name": "python", "quote": "strong Python and PyTorch skills"},
                {"name": "Kubernetes", "quote": "Nice to have: Kubernetes"},
            ],
        }
    )

    req = await extract_requirements(llm, description=DESCRIPTION)  # type: ignore[arg-type]

    assert [s.name for s in req.preferred_skills] == ["Kubernetes"]


async def test_malformed_items_do_not_crash_extraction() -> None:
    llm = _FakeLLM(
        {
            "required_skills": ["Python", {"name": "", "quote": "x"}, None],
            "preferred_skills": [],
            "min_years_experience": "five",
        }
    )

    req = await extract_requirements(llm, description=DESCRIPTION)  # type: ignore[arg-type]

    assert req.required_skills == []


async def test_deal_breaker_hits_require_a_verifiable_quote() -> None:
    llm = _FakeLLM(
        {
            "hits": [
                {"deal_breaker": "weekend on-call", "quote": "On-call weekends are required"},
                {"deal_breaker": "relocation", "quote": "must relocate to Boston"},  # invented
            ]
        }
    )

    hits = await check_deal_breakers(
        llm,  # type: ignore[arg-type]
        deal_breakers="no weekend on-call; no relocation",
        description=DESCRIPTION,
    )

    assert [(h.deal_breaker, h.quote) for h in hits] == [
        ("weekend on-call", "On-call weekends are required")
    ]
