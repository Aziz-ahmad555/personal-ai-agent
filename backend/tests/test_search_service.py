import uuid
from datetime import date

from app.profile.models import Education, Preferences, Profile, Skill, SkillVersion, WorkExperience
from app.research.models import ResearchClaim, ResearchSource
from app.search.service import Candidate, build_results, dedupe_and_rank


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


def test_dedupe_and_rank_keeps_lowest_distance_per_owner() -> None:
    owner_id = _uuid()
    candidates = [
        Candidate(owner_type="work_experience", owner_id=owner_id, distance=0.4, chunk_text="a"),
        Candidate(owner_type="work_experience", owner_id=owner_id, distance=0.1, chunk_text="b"),
        Candidate(owner_type="work_experience", owner_id=owner_id, distance=0.3, chunk_text="c"),
    ]

    ranked = dedupe_and_rank(candidates)

    assert len(ranked) == 1
    assert ranked[0].chunk_text == "b"
    assert ranked[0].distance == 0.1


def test_dedupe_and_rank_sorts_by_distance_across_owners() -> None:
    a, b, c = _uuid(), _uuid(), _uuid()
    candidates = [
        Candidate(owner_type="bio", owner_id=a, distance=0.5, chunk_text="a"),
        Candidate(owner_type="claim", owner_id=b, distance=0.1, chunk_text="b"),
        Candidate(owner_type="education", owner_id=c, distance=0.3, chunk_text="c"),
    ]

    ranked = dedupe_and_rank(candidates)

    assert [c.owner_id for c in ranked] == [b, c, a]


def test_dedupe_and_rank_respects_limit() -> None:
    candidates = [
        Candidate(owner_type="bio", owner_id=_uuid(), distance=float(i), chunk_text=str(i))
        for i in range(5)
    ]

    ranked = dedupe_and_rank(candidates, limit=2)

    assert len(ranked) == 2
    assert [c.distance for c in ranked] == [0.0, 1.0]


def test_build_results_resolves_each_owner_type_to_real_fields() -> None:
    profile_id = _uuid()
    experience_id = _uuid()
    education_id = _uuid()
    skill_version_id = _uuid()
    preferences_id = _uuid()
    source_id = _uuid()
    claim_id = _uuid()
    query_id = _uuid()

    ranked = [
        Candidate(
            owner_type="bio", owner_id=profile_id, distance=0.1, chunk_text="ML engineer bio"
        ),
        Candidate(
            owner_type="work_experience",
            owner_id=experience_id,
            distance=0.2,
            chunk_text="Led the platform team.",
        ),
        Candidate(
            owner_type="education",
            owner_id=education_id,
            distance=0.3,
            chunk_text="BSc Computer Science",
        ),
        Candidate(
            owner_type="skill_evidence",
            owner_id=skill_version_id,
            distance=0.4,
            chunk_text="PyTorch (advanced): shipped a CV pipeline",
        ),
        Candidate(
            owner_type="preferences",
            owner_id=preferences_id,
            distance=0.5,
            chunk_text="Remote, full_time",
        ),
        Candidate(
            owner_type="claim",
            owner_id=claim_id,
            distance=0.6,
            chunk_text="Requires 5 years PyTorch",
        ),
        Candidate(
            owner_type="source_chunk",
            owner_id=source_id,
            distance=0.7,
            chunk_text="Acme careers page text",
        ),
    ]

    skill = Skill(id=_uuid(), profile_id=profile_id, name="PyTorch")
    skill_version = SkillVersion(
        id=skill_version_id, skill_id=skill.id, level="advanced", evidence="shipped a CV pipeline"
    )
    skill_version.skill = skill

    claim = ResearchClaim(
        id=claim_id,
        query_id=query_id,
        claim_text="Requires 5 years PyTorch",
        status="corroborated",
        confidence_score=80,
        confidence_rationale="...",
    )
    source = ResearchSource(
        id=source_id,
        normalized_url="https://acme.example.com/careers",
        original_url="https://acme.example.com/careers",
        domain="acme.example.com",
        title="Acme Careers",
        tier="unknown",
        tier_rationale="...",
    )

    results = build_results(
        ranked,
        profiles={profile_id: Profile(id=profile_id, headline="ML Engineer")},
        experiences={
            experience_id: WorkExperience(
                id=experience_id,
                company="Acme",
                title="Staff Engineer",
                start_date=date(2022, 1, 1),
            )
        },
        educations={
            education_id: Education(id=education_id, institution="State University", degree="BSc")
        },
        skill_versions={skill_version_id: skill_version},
        preferences={preferences_id: Preferences(id=preferences_id)},
        sources={source_id: source},
        claims={claim_id: claim},
        source_query_ids={source_id: query_id},
    )

    by_type = {r.type: r for r in results}

    assert by_type["bio"].id == f"bio:{profile_id}"
    assert by_type["bio"].title == "ML Engineer"
    assert by_type["bio"].link.kind == "profile"

    assert by_type["work_experience"].title == "Staff Engineer · Acme"
    assert by_type["education"].title == "State University"
    assert by_type["skill_evidence"].title == "PyTorch · advanced"
    assert by_type["preferences"].title == "Preferences"

    assert by_type["research_claim"].title == "Requires 5 years PyTorch"
    assert by_type["research_claim"].link.kind == "research"
    assert by_type["research_claim"].link.query_id == str(query_id)
    assert by_type["research_claim"].link.anchor == f"claim-{claim_id}"

    assert by_type["research_source"].title == "Acme Careers"
    assert by_type["research_source"].link.query_id == str(query_id)
    assert by_type["research_source"].link.anchor == f"source-{source_id}"

    # Results stay in distance order, not insertion/grouping order.
    assert [r.type for r in results] == [
        "bio",
        "work_experience",
        "education",
        "skill_evidence",
        "preferences",
        "research_claim",
        "research_source",
    ]


def test_build_results_skips_hits_whose_owner_row_is_missing() -> None:
    missing_id = _uuid()
    ranked = [Candidate(owner_type="bio", owner_id=missing_id, distance=0.1, chunk_text="x")]

    results = build_results(
        ranked,
        profiles={},
        experiences={},
        educations={},
        skill_versions={},
        preferences={},
        sources={},
        claims={},
        source_query_ids={},
    )

    assert results == []


def test_build_results_research_source_with_no_resolvable_query_has_no_link_target() -> None:
    """A source could in principle survive with no query still referencing it (queries
    aren't deletable via the API today, so this shouldn't happen in practice, but the
    resolver must degrade to an unclickable result rather than a broken link)."""
    source_id = _uuid()
    source = ResearchSource(
        id=source_id,
        normalized_url="https://example.com",
        original_url="https://example.com",
        domain="example.com",
        title="Example",
        tier="unknown",
        tier_rationale="...",
    )
    ranked = [
        Candidate(owner_type="source_chunk", owner_id=source_id, distance=0.1, chunk_text="x")
    ]

    results = build_results(
        ranked,
        profiles={},
        experiences={},
        educations={},
        skill_versions={},
        preferences={},
        sources={source_id: source},
        claims={},
        source_query_ids={},
    )

    assert len(results) == 1
    assert results[0].link.query_id is None
    assert results[0].link.anchor is None
