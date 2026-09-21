"""Deterministic confidence scoring. The score and its rationale are both computed from
the same stored inputs — the rationale is templated, not a second LLM call re-describing
its own work, so it can never drift from what actually backs the claim.

A claim with no verified citation is forced to 0 / "unverified" regardless of every other
input: an unverifiable quote means there is no real evidence, full stop.
"""

from dataclasses import dataclass

from app.research.tiers import TIER_RANK

RECENCY_BUCKETS = (
    (7, 10, "within the last week"),
    (30, 5, "within the last month"),
    (180, 0, "within the last 6 months"),
    (None, -5, "more than 6 months old"),
)


@dataclass(frozen=True)
class ScoredClaim:
    status: str
    confidence_score: int
    rationale: str


def _recency_bucket(age_days: float | None) -> tuple[int, str]:
    if age_days is None:
        return 0, "publish date unknown"
    for max_days, points, label in RECENCY_BUCKETS:
        if max_days is None or age_days <= max_days:
            return points, f"freshest source is {label}"
    return 0, "publish date unknown"  # unreachable, satisfies type checker


def score_claim(
    *,
    best_tier: str,
    independent_corroborations: int,
    all_citations_verified: bool,
    has_contradiction: bool,
    newest_source_age_days: float | None,
) -> ScoredClaim:
    tier_rank = TIER_RANK.get(best_tier, 0)

    if not all_citations_verified or independent_corroborations == 0:
        return ScoredClaim(
            status="unverified",
            confidence_score=0,
            rationale=(
                "No citation for this claim could be verified against the stored source "
                "text — treated as unverified rather than asserted."
            ),
        )

    recency_points, recency_label = _recency_bucket(newest_source_age_days)
    corroboration_bonus = min(independent_corroborations - 1, 3) * 8

    score = tier_rank * 15 + corroboration_bonus + recency_points

    status = "corroborated" if independent_corroborations >= 2 else "single_source"
    if has_contradiction:
        score = max(score - 30, 0)
        status = "contradicted"

    score = max(0, min(100, score))

    rationale = (
        f"Best supporting source tier: {best_tier} ({tier_rank}/5). "
        f"Corroborated by {independent_corroborations} independent source(s). "
        f"{recency_label.capitalize()}. "
        f"All cited excerpts verified against stored source text."
    )
    if has_contradiction:
        rationale += " At least one source contradicts this claim — confidence reduced accordingly."

    return ScoredClaim(status=status, confidence_score=score, rationale=rationale)
