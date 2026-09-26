"""app.research.report.draft_report: regression tests for the citation-stripping fix (an eval-
harness finding, now closed) — a sentence whose citation marker doesn't resolve to a real claim
id must be dropped whole, not just have its bracket stripped, since "The role pays $200k
[bogus]" reduced to "The role pays $200k" is exactly as unattributed an assertion as one with
no citation at all."""

from typing import Any

from app.research.report import ClaimForReport, draft_report


class _FakeLLM:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    async def generate_structured(self, **kwargs: Any) -> dict[str, Any]:
        return self._payload


CLAIM = ClaimForReport(
    id="c1", claim_text="Kubernetes is preferred.", status="single_source", confidence_score=55
)


async def test_a_sentence_with_a_real_marker_survives_intact() -> None:
    llm = _FakeLLM({"summary": "Kubernetes is listed as preferred [c1].", "uncertainties": []})

    draft = await draft_report(llm, query_text="q", purpose=None, claims=[CLAIM])

    assert draft.summary == "Kubernetes is listed as preferred [c1]."
    assert draft.referenced_claim_ids == ["c1"]


async def test_a_sentence_with_an_unresolved_marker_is_dropped_whole_not_just_the_bracket() -> None:
    llm = _FakeLLM(
        {"summary": "The role pays $200k [bogus].", "uncertainties": []}
    )

    draft = await draft_report(llm, query_text="q", purpose=None, claims=[CLAIM])

    assert "[bogus]" not in draft.summary
    assert "$200k" not in draft.summary  # the fix: not just the bracket, the whole sentence
    assert draft.referenced_claim_ids == []


async def test_a_good_sentence_survives_alongside_a_dropped_bad_one() -> None:
    llm = _FakeLLM(
        {
            "summary": (
                "Kubernetes is listed as preferred [c1]. The role pays $200k [bogus]."
            ),
            "uncertainties": [],
        }
    )

    draft = await draft_report(llm, query_text="q", purpose=None, claims=[CLAIM])

    assert "Kubernetes is listed as preferred [c1]." in draft.summary
    assert "$200k" not in draft.summary
    assert draft.referenced_claim_ids == ["c1"]


async def test_a_sentence_with_one_good_and_one_bad_marker_is_dropped_entirely() -> None:
    """Can't cleanly trust half a sentence — if any citation in it fails to resolve, the
    whole sentence goes, even though [c1] itself is real."""
    llm = _FakeLLM(
        {
            "summary": "Kubernetes is preferred [c1], and salary is $200k [bogus].",
            "uncertainties": [],
        }
    )

    draft = await draft_report(llm, query_text="q", purpose=None, claims=[CLAIM])

    assert draft.summary == "The available claims did not yield a clear summary."
    assert draft.referenced_claim_ids == []


async def test_a_sentence_with_no_marker_at_all_is_left_untouched() -> None:
    """Documents a separate, harder problem this fix doesn't attempt to solve: a sentence
    with no citation whatsoever is a different failure mode than a citation that fails to
    resolve, and isn't caught here."""
    llm = _FakeLLM(
        {"summary": "The hiring manager is Sarah Chen.", "uncertainties": []}
    )

    draft = await draft_report(llm, query_text="q", purpose=None, claims=[CLAIM])

    assert draft.summary == "The hiring manager is Sarah Chen."
    assert draft.referenced_claim_ids == []


async def test_empty_claims_short_circuits_without_calling_the_model() -> None:
    calls = {"count": 0}

    class _CountingLLM:
        async def generate_structured(self, **kwargs: Any) -> dict[str, Any]:
            calls["count"] += 1
            return {"summary": "should never be called", "uncertainties": []}

    draft = await draft_report(_CountingLLM(), query_text="q", purpose=None, claims=[])

    assert calls["count"] == 0
    assert draft.summary == "No verified claims were found for this query."
    assert draft.referenced_claim_ids == []
