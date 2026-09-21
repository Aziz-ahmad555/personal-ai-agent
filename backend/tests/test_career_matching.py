"""Pure scoring tests — no DB, no LLM. The properties that matter most: unknowns are left out
of the score (never zeroed or guessed), the low-confidence flag tracks how much of the 100
points was actually measurable, and every point traces to a specific fact."""

from datetime import date

from app.career.matching import (
    LOW_CONFIDENCE_ASSESSED_WEIGHT,
    WEIGHTS,
    EducationFact,
    FuzzyMatch,
    JobFacts,
    PreferenceFacts,
    ProfileFacts,
    SkillFact,
    education_level_of,
    experience_years,
    normalize_skill,
    score_match,
)
from app.career.requirements import JobRequirements, QuotedSkill


def _skill(name: str, level: str = "advanced") -> SkillFact:
    return SkillFact(name=name, level=level, evidence=f"Shipped production work using {name}.")


def _req(*names: str) -> list[QuotedSkill]:
    return [QuotedSkill(name=n, quote=f"experience with {n}") for n in names]


def _component(result, key):  # type: ignore[no-untyped-def]
    return next(c for c in result.components if c.key == key)


def test_weights_sum_to_100() -> None:
    assert sum(WEIGHTS.values()) == 100


def test_full_skill_match_scores_100_when_only_skills_are_assessable() -> None:
    requirements = JobRequirements(required_skills=_req("Python", "PyTorch"))
    profile = ProfileFacts(skills=(_skill("Python"), _skill("PyTorch")))

    result = score_match(requirements, profile, JobFacts())

    assert result.score_percent == 100
    assert result.assessed_weight == WEIGHTS["required_skills"]


def test_missing_skill_lowers_score_and_is_reported_missing() -> None:
    requirements = JobRequirements(required_skills=_req("Python", "Rust"))
    profile = ProfileFacts(skills=(_skill("Python"),))

    result = score_match(requirements, profile, JobFacts())
    component = _component(result, "required_skills")

    assert result.score_percent == 50
    types = {d["requirement"]: d["match_type"] for d in component.details}
    assert types == {"Python": "exact", "Rust": "missing"}


def test_exact_match_carries_the_profile_evidence() -> None:
    requirements = JobRequirements(required_skills=_req("Python"))
    profile = ProfileFacts(skills=(_skill("Python"),))

    component = _component(score_match(requirements, profile, JobFacts()), "required_skills")
    detail = component.details[0]

    assert detail["evidence"] == "Shipped production work using Python."
    assert detail["quote"] == "experience with Python"


def test_aliases_count_as_exact_matches() -> None:
    assert normalize_skill("Torch") == normalize_skill("PyTorch")
    assert normalize_skill("K8s") == "kubernetes"
    requirements = JobRequirements(required_skills=_req("Kubernetes"))
    profile = ProfileFacts(skills=(_skill("k8s"),))

    component = _component(score_match(requirements, profile, JobFacts()), "required_skills")
    detail = component.details[0]

    assert detail["match_type"] == "exact"


def test_fuzzy_match_gets_labeled_reduced_credit() -> None:
    requirements = JobRequirements(required_skills=_req("TensorFlow"))
    profile = ProfileFacts(skills=(_skill("PyTorch"),))
    fuzzy = {normalize_skill("TensorFlow"): FuzzyMatch(profile_skill="PyTorch", similarity=0.83)}

    result = score_match(requirements, profile, JobFacts(), fuzzy=fuzzy)
    component = _component(result, "required_skills")

    assert result.score_percent == 50  # FUZZY_CREDIT = 0.5, not a full match
    assert component.details[0]["match_type"] == "similar"
    assert component.details[0]["profile_skill"] == "PyTorch"
    assert "similar" in component.summary


def test_profile_with_no_evidenced_skills_is_not_assessed_rather_than_zero() -> None:
    requirements = JobRequirements(required_skills=_req("Python"))

    result = score_match(requirements, ProfileFacts(), JobFacts())
    component = _component(result, "required_skills")

    assert component.status == "not_assessed"
    assert result.score_percent is None  # nothing measurable — "I can't tell", not 0


def test_unevidenced_skill_is_missing_with_an_explanatory_note() -> None:
    requirements = JobRequirements(required_skills=_req("Python", "Go"))
    profile = ProfileFacts(skills=(_skill("Python"),), unevidenced_skill_names=("Go",))

    component = _component(score_match(requirements, profile, JobFacts()), "required_skills")
    detail = component.details[1]

    assert detail["match_type"] == "missing"
    assert "no evidence" in detail["note"]


def test_component_with_nothing_in_the_posting_is_excluded_not_zeroed() -> None:
    requirements = JobRequirements(required_skills=_req("Python"))  # no years/education/etc.
    profile = ProfileFacts(skills=(_skill("Python"),), experience_years=10.0)

    result = score_match(requirements, profile, JobFacts())

    assert _component(result, "experience").status == "not_assessed"
    assert _component(result, "education").status == "not_assessed"
    assert result.score_percent == 100
    assert any(u.startswith("Years of experience:") for u in result.uncertainties)


def test_low_confidence_flag_tracks_assessed_weight() -> None:
    # Only required skills (35/100) measurable -> below the threshold.
    sparse = score_match(
        JobRequirements(required_skills=_req("Python")),
        ProfileFacts(skills=(_skill("Python"),)),
        JobFacts(),
    )
    assert sparse.assessed_weight == 35
    assert sparse.low_confidence is True

    # Skills (35) + experience (20) = 55 -> right at the threshold, no longer low confidence.
    richer = score_match(
        JobRequirements(
            required_skills=_req("Python"), min_years_experience=3, min_years_quote="3+ years"
        ),
        ProfileFacts(skills=(_skill("Python"),), experience_years=5.0),
        JobFacts(),
    )
    assert richer.assessed_weight == 55 == LOW_CONFIDENCE_ASSESSED_WEIGHT
    assert richer.low_confidence is False


def test_nothing_assessable_gives_no_score_and_low_confidence() -> None:
    result = score_match(JobRequirements(), ProfileFacts(), JobFacts())

    assert result.score_percent is None
    assert result.assessed_weight == 0
    assert result.low_confidence is True
    assert len(result.uncertainties) == len(WEIGHTS)


def test_experience_shortfall_is_proportional() -> None:
    requirements = JobRequirements(min_years_experience=8, min_years_quote="8+ years")
    profile = ProfileFacts(experience_years=4.0)

    component = _component(score_match(requirements, profile, JobFacts()), "experience")

    assert component.fraction == 0.5
    assert "falls short" in component.summary


def test_experience_not_assessed_without_work_history() -> None:
    requirements = JobRequirements(min_years_experience=3, min_years_quote="3+ years")

    component = _component(score_match(requirements, ProfileFacts(), JobFacts()), "experience")

    assert component.status == "not_assessed"
    assert "no work-history" in component.reason


def test_experience_years_merges_overlapping_roles() -> None:
    today = date(2026, 1, 1)
    spans = [
        (date(2020, 1, 1), date(2022, 1, 1)),
        (date(2021, 1, 1), date(2023, 1, 1)),  # overlaps the first by a year
        (date(2024, 1, 1), None),  # ongoing
    ]

    assert experience_years(spans, today=today) == 5.0  # 2020-2023 (3y) + 2024-2026 (2y)
    assert experience_years([], today=today) is None


def test_work_mode_and_location() -> None:
    profile = ProfileFacts(
        preferences=PreferenceFacts(remote_preference="remote", locations=("Austin",))
    )

    remote = _component(
        score_match(JobRequirements(), profile, JobFacts(remote_type="remote")),
        "work_mode_location",
    )
    onsite_elsewhere = _component(
        score_match(
            JobRequirements(),
            profile,
            JobFacts(remote_type="onsite", location="Denver, CO"),
        ),
        "work_mode_location",
    )
    hybrid = _component(
        score_match(
            JobRequirements(), profile, JobFacts(remote_type="hybrid", location="Austin, TX")
        ),
        "work_mode_location",
    )

    assert remote.fraction == 1.0  # remote job: location is irrelevant
    assert onsite_elsewhere.fraction == 0.0
    assert hybrid.fraction == 0.75  # hybrid vs remote pref = 0.5, Austin matches = 1.0


def test_work_mode_not_assessed_when_posting_is_silent() -> None:
    profile = ProfileFacts(preferences=PreferenceFacts(remote_preference="remote"))

    result = score_match(JobRequirements(), profile, JobFacts())
    component = _component(result, "work_mode_location")

    assert component.status == "not_assessed"


def test_salary_not_published_is_an_uncertainty_not_a_zero() -> None:
    profile = ProfileFacts(preferences=PreferenceFacts(salary_min=120_000))

    result = score_match(JobRequirements(), profile, JobFacts())

    assert _component(result, "salary").status == "not_assessed"
    assert "Salary: the posting doesn't publish a salary." in result.uncertainties


def test_salary_meets_and_misses() -> None:
    profile = ProfileFacts(preferences=PreferenceFacts(salary_min=100_000))

    meets = _component(
        score_match(JobRequirements(), profile, JobFacts(salary_min=90_000, salary_max=130_000)),
        "salary",
    )
    misses = _component(
        score_match(JobRequirements(), profile, JobFacts(salary_min=60_000, salary_max=80_000)),
        "salary",
    )

    assert meets.fraction == 1.0
    assert misses.fraction == 0.8


def test_salary_notes_when_currency_is_not_usd() -> None:
    profile = ProfileFacts(preferences=PreferenceFacts(salary_min=100_000))

    component = _component(
        score_match(
            JobRequirements(), profile, JobFacts(salary_max=120_000, salary_currency="EUR")
        ),
        "salary",
    )

    assert "without currency conversion" in component.summary


def test_industry_include_exclude_and_unknown() -> None:
    prefs = PreferenceFacts(industries_include=("healthcare",), industries_exclude=("gambling",))
    profile = ProfileFacts(preferences=prefs)

    def industry(name: str | None):  # type: ignore[no-untyped-def]
        req = JobRequirements(industry=name, industry_quote="q" if name else None)
        return _component(score_match(req, profile, JobFacts()), "industry")

    assert industry("Digital Healthcare").fraction == 1.0
    assert industry("Online Gambling").fraction == 0.0
    assert industry("Logistics").fraction == 0.0  # has an include list, this isn't on it
    assert industry(None).status == "not_assessed"


def test_education_levels() -> None:
    assert education_level_of("B.S. Computer Science") == "bachelor"
    assert education_level_of("Master of Science") == "master"
    assert education_level_of("PhD") == "doctorate"
    assert education_level_of("Certificate in Welding") is None

    requirements = JobRequirements(education_level="bachelor", education_quote="Bachelor's degree")
    meets = ProfileFacts(educations=(EducationFact(degree="MSc", field="CS"),))
    short = ProfileFacts(educations=(EducationFact(degree="Associate of Arts", field=None),))
    unclear = ProfileFacts(educations=(EducationFact(degree="Certificate", field=None),))

    assert _component(score_match(requirements, meets, JobFacts()), "education").fraction == 1.0
    assert _component(score_match(requirements, short, JobFacts()), "education").fraction == 0.0
    assert _component(score_match(requirements, unclear, JobFacts()), "education").status == (
        "not_assessed"
    )


def test_dropped_unverified_requirements_are_surfaced() -> None:
    requirements = JobRequirements(required_skills=_req("Python"), dropped_unverified=2)

    result = score_match(requirements, ProfileFacts(skills=(_skill("Python"),)), JobFacts())

    assert any("2 extracted requirement(s) were discarded" in u for u in result.uncertainties)
