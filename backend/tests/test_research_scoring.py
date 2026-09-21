from app.research.scoring import score_claim


def test_unverified_citation_forces_zero_score_regardless_of_other_inputs() -> None:
    scored = score_claim(
        best_tier="official",
        independent_corroborations=3,
        all_citations_verified=False,
        has_contradiction=False,
        newest_source_age_days=0,
    )
    assert scored.status == "unverified"
    assert scored.confidence_score == 0


def test_no_corroboration_forces_unverified() -> None:
    scored = score_claim(
        best_tier="official",
        independent_corroborations=0,
        all_citations_verified=True,
        has_contradiction=False,
        newest_source_age_days=0,
    )
    assert scored.status == "unverified"
    assert scored.confidence_score == 0


def test_single_verified_source_is_single_source_status() -> None:
    scored = score_claim(
        best_tier="reputable_secondary",
        independent_corroborations=1,
        all_citations_verified=True,
        has_contradiction=False,
        newest_source_age_days=1,
    )
    assert scored.status == "single_source"
    assert scored.confidence_score > 0


def test_multiple_independent_sources_marks_corroborated_and_scores_higher() -> None:
    single = score_claim(
        best_tier="official",
        independent_corroborations=1,
        all_citations_verified=True,
        has_contradiction=False,
        newest_source_age_days=1,
    )
    corroborated = score_claim(
        best_tier="official",
        independent_corroborations=3,
        all_citations_verified=True,
        has_contradiction=False,
        newest_source_age_days=1,
    )
    assert corroborated.status == "corroborated"
    assert corroborated.confidence_score > single.confidence_score


def test_higher_tier_scores_higher_than_lower_tier() -> None:
    official = score_claim(
        best_tier="official",
        independent_corroborations=1,
        all_citations_verified=True,
        has_contradiction=False,
        newest_source_age_days=1,
    )
    forum = score_claim(
        best_tier="forum_anecdotal",
        independent_corroborations=1,
        all_citations_verified=True,
        has_contradiction=False,
        newest_source_age_days=1,
    )
    assert official.confidence_score > forum.confidence_score


def test_contradiction_reduces_score_and_sets_status() -> None:
    scored = score_claim(
        best_tier="official",
        independent_corroborations=2,
        all_citations_verified=True,
        has_contradiction=True,
        newest_source_age_days=1,
    )
    assert scored.status == "contradicted"
    assert "contradicts" in scored.rationale


def test_score_is_clamped_between_zero_and_hundred() -> None:
    scored = score_claim(
        best_tier="official",
        independent_corroborations=10,
        all_citations_verified=True,
        has_contradiction=False,
        newest_source_age_days=0,
    )
    assert 0 <= scored.confidence_score <= 100


def test_older_source_scores_lower_than_fresh_source() -> None:
    fresh = score_claim(
        best_tier="docs",
        independent_corroborations=1,
        all_citations_verified=True,
        has_contradiction=False,
        newest_source_age_days=1,
    )
    stale = score_claim(
        best_tier="docs",
        independent_corroborations=1,
        all_citations_verified=True,
        has_contradiction=False,
        newest_source_age_days=400,
    )
    assert fresh.confidence_score > stale.confidence_score
