"""Weighted job-to-profile match scoring — pure, deterministic code; no LLM, no I/O.

The LLM's only job upstream (app.career.requirements) is to *read* a posting into quoted,
verified requirements. Turning those into a number happens here, so a score is always
reproducible and every point is traceable to a specific profile fact and a specific quote.

Design rules, straight from the project brief ("if evidence isn't available, say I don't
know"):
- A component is either "assessed" or "not_assessed". Not-assessed components (the posting
  doesn't state the thing, or the profile doesn't hold it) are excluded from the score's
  denominator and listed as uncertainties — never scored as 0 and never guessed.
- `assessed_weight` is how many of the 100 points were actually measurable. When it is low
  the score is flagged `low_confidence`, so a percentage can't look more authoritative than
  the evidence behind it.
- Skill matching is never keyword-only in spirit: exact/alias matches get full credit, and
  an embedding-similar skill (computed by the caller) gets a labeled, reduced credit.
"""

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.career.requirements import EDUCATION_LEVELS, JobRequirements, QuotedSkill

WEIGHTS: dict[str, int] = {
    "required_skills": 35,
    "experience": 20,
    "preferred_skills": 10,
    "work_mode_location": 10,
    "salary": 10,
    "industry": 10,
    "education": 5,
}
assert sum(WEIGHTS.values()) == 100

LABELS: dict[str, str] = {
    "required_skills": "Required skills",
    "experience": "Years of experience",
    "preferred_skills": "Preferred skills",
    "work_mode_location": "Work mode & location",
    "salary": "Salary",
    "industry": "Industry",
    "education": "Education",
}

# A similar-but-not-identical skill (found by embedding similarity) counts for this much of
# a full match. Deliberately well under 1: similarity is weaker evidence than the candidate
# actually listing the skill.
FUZZY_CREDIT = 0.5

# Below this many of the 100 points actually measurable, the score is flagged
# low-confidence (the UI shows a prominent warning instead of just a percentage).
LOW_CONFIDENCE_ASSESSED_WEIGHT = 55

_SKILL_ALIASES: dict[str, str] = {
    "js": "javascript",
    "ecmascript": "javascript",
    "ts": "typescript",
    "py": "python",
    "python3": "python",
    "torch": "pytorch",
    "tf": "tensorflow",
    "sklearn": "scikit-learn",
    "scikit learn": "scikit-learn",
    "postgres": "postgresql",
    "psql": "postgresql",
    "k8s": "kubernetes",
    "golang": "go",
    "node": "nodejs",
    "node.js": "nodejs",
    "reactjs": "react",
    "react.js": "react",
    "vuejs": "vue",
    "vue.js": "vue",
    "ml": "machine learning",
    "cv": "computer vision",
    "nlp": "natural language processing",
    "aws": "amazon web services",
    "gcp": "google cloud",
    "c sharp": "c#",
    "cpp": "c++",
}

_EDUCATION_RANK = {level: rank for rank, level in enumerate(EDUCATION_LEVELS)}
_DEGREE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("doctorate", re.compile(r"\b(ph\.?\s?d|doctor(ate|al)?|d\.?phil)\b", re.I)),
    ("master", re.compile(r"\b(master'?s?|m\.?sc?|m\.?eng|m\.?b\.?a|m\.?a)\b", re.I)),
    (
        "bachelor",
        re.compile(r"\b(bachelor'?s?|b\.?sc?|b\.?eng|b\.?a|b\.?tech|undergraduate)\b", re.I),
    ),
    ("associate", re.compile(r"\b(associate'?s?|a\.?a\.?s?)\b", re.I)),
    ("high_school", re.compile(r"\b(high school|secondary school|g\.?e\.?d|diploma)\b", re.I)),
]


@dataclass(frozen=True)
class SkillFact:
    name: str
    level: str
    evidence: str


@dataclass(frozen=True)
class EducationFact:
    degree: str | None
    field: str | None


@dataclass(frozen=True)
class PreferenceFacts:
    remote_preference: str = "no_preference"
    locations: tuple[str, ...] = ()
    salary_min: int | None = None
    salary_max: int | None = None
    industries_include: tuple[str, ...] = ()
    industries_exclude: tuple[str, ...] = ()
    deal_breakers: str | None = None


@dataclass(frozen=True)
class ProfileFacts:
    # Only skills that have at least one evidence-backed version — an assertion with no
    # evidence recorded is not something we score a job against.
    skills: tuple[SkillFact, ...] = ()
    unevidenced_skill_names: tuple[str, ...] = ()
    # None when the profile has no work-history entries at all (unknown, not "0 years").
    experience_years: float | None = None
    educations: tuple[EducationFact, ...] = ()
    preferences: PreferenceFacts = field(default_factory=PreferenceFacts)


@dataclass(frozen=True)
class JobFacts:
    remote_type: str = "unknown"
    location: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str | None = None


@dataclass(frozen=True)
class FuzzyMatch:
    profile_skill: str
    similarity: float


@dataclass
class ComponentResult:
    key: str
    label: str
    weight: int
    status: str  # "assessed" | "not_assessed"
    fraction: float | None = None
    points: float | None = None
    summary: str = ""
    reason: str | None = None  # why not assessed
    details: list[dict[str, Any]] = field(default_factory=list)
    # Things this component couldn't verify even though it was assessed; surfaced in the
    # match's uncertainties list, not stored on the component itself.
    caveats: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "weight": self.weight,
            "status": self.status,
            "fraction": self.fraction,
            "points": self.points,
            "summary": self.summary,
            "reason": self.reason,
            "details": self.details,
        }


@dataclass
class MatchResult:
    score_percent: int | None
    assessed_weight: int
    low_confidence: bool
    components: list[ComponentResult]
    uncertainties: list[str]


def normalize_skill(name: str) -> str:
    cleaned = re.sub(r"[^\w+#.\- ]", " ", name.lower())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return _SKILL_ALIASES.get(cleaned, cleaned)


def skill_variants(name: str) -> set[str]:
    """Every spelling that counts as the same skill (the name itself, its canonical form, and
    known aliases), lower-cased — for finding a skill mentioned in free text."""
    canonical = normalize_skill(name)
    variants = {canonical, name.strip().lower()}
    variants.update(alias for alias, canon in _SKILL_ALIASES.items() if canon == canonical)
    return {v for v in variants if v}


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def experience_years(spans: list[tuple[date, date | None]], *, today: date) -> float | None:
    """Total years of work history, with overlapping/concurrent roles merged so two jobs held
    at once aren't double counted. None when there are no entries (unknown, not zero)."""
    if not spans:
        return None
    intervals = sorted(
        (start, min(end or today, today)) for start, end in spans if start <= (end or today)
    )
    if not intervals:
        return 0.0
    merged: list[tuple[date, date]] = []
    for start, end in intervals:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    total_days = sum((end - start).days for start, end in merged)
    return round(total_days / 365.25, 1)


def education_level_of(degree: str | None) -> str | None:
    if not degree:
        return None
    for level, pattern in _DEGREE_PATTERNS:
        if pattern.search(degree):
            return level
    return None


def _not_assessed(key: str, reason: str) -> ComponentResult:
    return ComponentResult(
        key=key, label=LABELS[key], weight=WEIGHTS[key], status="not_assessed", reason=reason
    )


def _assessed(
    key: str, fraction: float, summary: str, details: list[dict[str, Any]]
) -> ComponentResult:
    fraction = max(0.0, min(1.0, fraction))
    return ComponentResult(
        key=key,
        label=LABELS[key],
        weight=WEIGHTS[key],
        status="assessed",
        fraction=round(fraction, 3),
        points=round(WEIGHTS[key] * fraction, 1),
        summary=summary,
        details=details,
    )


def _skills_component(
    key: str,
    requested: list[QuotedSkill],
    profile: ProfileFacts,
    fuzzy: dict[str, FuzzyMatch],
) -> ComponentResult:
    if not requested:
        return _not_assessed(
            key, "the posting doesn't state any skills of this kind (with a verifiable quote)."
        )

    if not profile.skills:
        # No skills on file is unknown, not "0 of N" — scoring it as a total miss would let
        # an empty profile masquerade as a measured mismatch.
        return _not_assessed(key, "your profile has no evidence-backed skills recorded yet.")

    by_name = {normalize_skill(skill.name): skill for skill in profile.skills}
    unevidenced = {normalize_skill(name) for name in profile.unevidenced_skill_names}

    credit = 0.0
    exact = similar = missing = 0
    details: list[dict[str, Any]] = []
    for req in requested:
        norm = normalize_skill(req.name)
        detail: dict[str, Any] = {"requirement": req.name, "quote": req.quote}
        if norm in by_name:
            fact = by_name[norm]
            credit += 1.0
            exact += 1
            detail.update(
                match_type="exact",
                profile_skill=fact.name,
                level=fact.level,
                evidence=fact.evidence,
            )
        elif norm in fuzzy:
            match = fuzzy[norm]
            similar_fact = next((s for s in profile.skills if s.name == match.profile_skill), None)
            credit += FUZZY_CREDIT
            similar += 1
            detail.update(
                match_type="similar",
                profile_skill=match.profile_skill,
                similarity=round(match.similarity, 2),
                level=similar_fact.level if similar_fact else None,
                evidence=similar_fact.evidence if similar_fact else None,
            )
        else:
            missing += 1
            detail.update(match_type="missing")
            if norm in unevidenced:
                detail["note"] = (
                    "This skill is in your profile but has no evidence recorded, so it isn't "
                    "counted."
                )
        details.append(detail)

    parts = [f"{exact} exact"]
    if similar:
        parts.append(f"{similar} similar (partial credit)")
    parts.append(f"{missing} missing")
    summary = f"{len(requested)} listed: " + ", ".join(parts) + "."
    return _assessed(key, credit / len(requested), summary, details)


def _experience_component(req: JobRequirements, profile: ProfileFacts) -> ComponentResult:
    key = "experience"
    if req.min_years_experience is None:
        return _not_assessed(key, "the posting doesn't state a minimum years of experience.")
    if profile.experience_years is None:
        return _not_assessed(key, "your profile has no work-history entries to measure against.")

    needed = req.min_years_experience
    have = profile.experience_years
    fraction = 1.0 if needed == 0 else min(1.0, have / needed)
    verdict = "meets" if have >= needed else "falls short of"
    return _assessed(
        key,
        fraction,
        f"Your work history totals {have:g} years, which {verdict} the {needed} required.",
        [
            {
                "requirement": f"{needed}+ years",
                "quote": req.min_years_quote,
                "profile_years": have,
            }
        ],
    )


def _work_mode_location_component(job: JobFacts, profile: ProfileFacts) -> ComponentResult:
    key = "work_mode_location"
    prefs = profile.preferences
    checks: list[float] = []
    details: list[dict[str, Any]] = []
    unverifiable: list[str] = []

    if job.remote_type != "unknown" and prefs.remote_preference != "no_preference":
        if job.remote_type == prefs.remote_preference:
            score = 1.0
        elif "hybrid" in (job.remote_type, prefs.remote_preference):
            score = 0.5  # hybrid sits between remote and onsite
        else:
            score = 0.0
        checks.append(score)
        details.append(
            {
                "check": "work mode",
                "posting": job.remote_type,
                "preference": prefs.remote_preference,
                "fraction": score,
            }
        )

    # Location only matters when the role isn't fully remote.
    if job.remote_type != "remote" and prefs.locations and job.location:
        job_loc = _normalize_text(job.location)
        hit = next(
            (
                loc
                for loc in prefs.locations
                if _normalize_text(loc) in job_loc or job_loc in _normalize_text(loc)
            ),
            None,
        )
        location_detail: dict[str, Any] = {
            "check": "location",
            "posting": job.location,
            "preference": ", ".join(prefs.locations),
            "matched": hit,
        }
        if hit:
            checks.append(1.0)
            location_detail["fraction"] = 1.0
        else:
            # Plain string matching can't tell that a city lies inside a preferred country
            # (or region), so "no textual match" is not evidence of a mismatch. Don't score
            # it as 0 — leave it out and say so.
            location_detail["note"] = (
                "No textual match, but this can't tell whether the posting's location lies "
                "inside one of your preferred places (e.g. a city within a country), so it "
                "isn't counted against you."
            )
            unverifiable.append(
                f"Location: '{job.location}' doesn't textually match your preferred "
                f"locations ({', '.join(prefs.locations)}); it may still be inside one."
            )
        details.append(location_detail)

    if not checks:
        result = _not_assessed(
            key,
            "the posting doesn't state a work mode/location, or your preferences don't "
            "constrain them, or its location couldn't be matched to your preferred places.",
        )
        result.details = details
        result.caveats = unverifiable
        return result
    fraction = sum(checks) / len(checks)
    result = _assessed(key, fraction, f"{len(checks)} check(s) against your preferences.", details)
    result.caveats = unverifiable
    return result


def _salary_component(job: JobFacts, profile: ProfileFacts) -> ComponentResult:
    key = "salary"
    upper = max((v for v in (job.salary_min, job.salary_max) if v is not None), default=None)
    desired = profile.preferences.salary_min
    if upper is None:
        return _not_assessed(key, "the posting doesn't publish a salary.")
    if desired is None:
        return _not_assessed(key, "you haven't set a minimum salary in your preferences.")

    fraction = min(1.0, upper / desired) if desired > 0 else 1.0
    detail: dict[str, Any] = {
        "posting_upper": upper,
        "currency": job.salary_currency,
        "your_minimum": desired,
    }
    summary = (
        f"Posting tops out at {upper:,}; your minimum is {desired:,}."
        if upper < desired
        else f"Posting reaches {upper:,}, meeting your {desired:,} minimum."
    )
    if job.salary_currency and job.salary_currency.upper() != "USD":
        # Preferences hold no currency; we compare the raw numbers, and say so.
        summary += f" (Compared without currency conversion — posting is in {job.salary_currency}.)"
    return _assessed(key, fraction, summary, [detail])


def _contains_any(text: str, terms: tuple[str, ...]) -> str | None:
    norm = _normalize_text(text)
    for term in terms:
        t = _normalize_text(term)
        if t and (t in norm or norm in t):
            return term
    return None


def _industry_component(req: JobRequirements, profile: ProfileFacts) -> ComponentResult:
    key = "industry"
    prefs = profile.preferences
    if not prefs.industries_include and not prefs.industries_exclude:
        return _not_assessed(key, "you haven't set industry preferences.")
    if req.industry is None:
        return _not_assessed(key, "the posting doesn't state its industry.")

    detail = {"posting_industry": req.industry, "quote": req.industry_quote}
    excluded = _contains_any(req.industry, prefs.industries_exclude)
    if excluded:
        return _assessed(
            key, 0.0, f"Industry '{req.industry}' is on your exclude list ('{excluded}').", [detail]
        )
    included = _contains_any(req.industry, prefs.industries_include)
    if included:
        return _assessed(
            key, 1.0, f"Industry '{req.industry}' matches your interest in '{included}'.", [detail]
        )
    if prefs.industries_include:
        return _assessed(
            key,
            0.0,
            f"Industry '{req.industry}' isn't among your preferred industries.",
            [detail],
        )
    # Only an exclude list exists, and this industry isn't on it.
    return _assessed(key, 1.0, f"Industry '{req.industry}' isn't one you exclude.", [detail])


def _education_component(req: JobRequirements, profile: ProfileFacts) -> ComponentResult:
    key = "education"
    if req.education_level is None:
        return _not_assessed(key, "the posting doesn't state an education requirement.")
    if not profile.educations:
        return _not_assessed(key, "your profile has no education entries.")

    levels = [education_level_of(e.degree) for e in profile.educations]
    known = [level for level in levels if level is not None]
    if not known:
        return _not_assessed(
            key,
            "none of your education entries have a degree this system could classify "
            "(e.g. Bachelor's, Master's).",
        )
    best = max(known, key=lambda level: _EDUCATION_RANK[level])
    needed = req.education_level
    met = _EDUCATION_RANK[best] >= _EDUCATION_RANK[needed]
    return _assessed(
        key,
        1.0 if met else 0.0,
        f"Posting asks for {needed.replace('_', ' ')}; your highest recorded is "
        f"{best.replace('_', ' ')}.",
        [{"requirement": needed, "quote": req.education_quote, "profile_level": best}],
    )


def score_match(
    requirements: JobRequirements,
    profile: ProfileFacts,
    job: JobFacts,
    *,
    fuzzy: dict[str, FuzzyMatch] | None = None,
) -> MatchResult:
    fuzzy = fuzzy or {}
    components = [
        _skills_component("required_skills", requirements.required_skills, profile, fuzzy),
        _experience_component(requirements, profile),
        _skills_component("preferred_skills", requirements.preferred_skills, profile, fuzzy),
        _work_mode_location_component(job, profile),
        _salary_component(job, profile),
        _industry_component(requirements, profile),
        _education_component(requirements, profile),
    ]

    assessed = [c for c in components if c.status == "assessed"]
    assessed_weight = sum(c.weight for c in assessed)
    earned = sum(c.points or 0.0 for c in assessed)
    score = round(100 * earned / assessed_weight) if assessed_weight else None

    uncertainties = [f"{c.label}: {c.reason}" for c in components if c.status == "not_assessed"]
    uncertainties.extend(caveat for c in components for caveat in c.caveats)
    if requirements.dropped_unverified:
        uncertainties.append(
            f"{requirements.dropped_unverified} extracted requirement(s) were discarded because "
            "their supporting quote couldn't be found in the posting."
        )

    return MatchResult(
        score_percent=score,
        assessed_weight=assessed_weight,
        low_confidence=assessed_weight < LOW_CONFIDENCE_ASSESSED_WEIGHT,
        components=components,
        uncertainties=uncertainties,
    )
