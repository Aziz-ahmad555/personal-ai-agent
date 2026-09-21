"""The checks that stop a fabricated claim reaching a resume. Each case is a way an LLM might
"helpfully" embellish; every one must be caught, while an honest rephrase must pass."""

from app.career.resume_base import ResumeBase, SkillItem
from app.career.resume_verify import (
    find_gaps,
    mentions_term,
    novel_terms,
    reorder_skills,
    verify_rewrite,
)

SOURCE = "Built a fraud detection web application using Flask, SQLAlchemy and XGBoost."


def _verify(new_text: str, **overrides):  # type: ignore[no-untyped-def]
    params = {
        "source_text": SOURCE,
        "new_text": new_text,
        "allowed_words": {"flask", "sqlalchemy", "xgboost"},
        "allowed_skill_norms": set(),
        "watch_terms": ["Kubernetes", "Python", "PyTorch"],
        **overrides,
    }
    return verify_rewrite(**params)


def test_an_honest_rephrase_passes() -> None:
    assert _verify("Developed a fraud detection web application with Flask and XGBoost.") is None


def test_sentence_start_words_are_not_mistaken_for_invented_names() -> None:
    assert _verify("Designed and shipped a fraud detection web application in Flask.") is None


def test_adding_a_number_is_rejected() -> None:
    reason = _verify("Built a fraud detection web application using Flask, cutting losses by 40%.")

    assert reason is not None
    assert "adds number(s)" in reason
    assert "40" in reason


def test_a_number_already_in_the_source_may_be_reused() -> None:
    source = "Reduced processing time from 12 hours to 3 hours using Flask."

    assert (
        verify_rewrite(
            source_text=source,
            new_text="Cut processing time from 12 hours to 3 hours with Flask.",
            allowed_words={"flask"},
            allowed_skill_norms=set(),
            watch_terms=[],
        )
        is None
    )


def test_claiming_a_posting_skill_the_item_doesnt_support_is_rejected() -> None:
    reason = _verify("Built a fraud detection web application deployed on Kubernetes.")

    assert reason is not None
    assert "claims 'Kubernetes'" in reason


def test_a_skill_the_item_is_entitled_to_may_be_used() -> None:
    # The user recorded evidence for Kubernetes pointing at this very role.
    assert (
        _verify(
            "Built a fraud detection web application deployed on Kubernetes.",
            allowed_skill_norms={"kubernetes"},
            allowed_words={"flask", "sqlalchemy", "xgboost", "kubernetes"},
        )
        is None
    )


def test_a_skill_alias_is_caught_too() -> None:
    reason = _verify("Built a fraud detection web application, tuning models in torch.")

    assert reason is not None
    assert "PyTorch" in reason


def test_an_invented_tool_outside_the_watch_list_is_still_caught() -> None:
    reason = _verify("Built a fraud detection web application, orchestrated with Terraform.")

    assert reason is not None
    assert "introduces" in reason
    assert "Terraform" in reason


def test_an_invented_acronym_is_caught() -> None:
    reason = _verify("Built a fraud detection web application on AWS with Flask.")

    assert reason is not None
    assert "AWS" in reason


def test_ballooning_length_is_rejected() -> None:
    padded = SOURCE + " " + "It was a really significant undertaking for the team overall. " * 6

    reason = _verify(padded)

    assert reason is not None
    assert "much longer" in reason


def test_an_empty_suggestion_is_rejected() -> None:
    assert _verify("   ") == "the suggestion was empty"


def test_mentions_term_respects_word_boundaries_and_symbols() -> None:
    assert mentions_term("Wrote services in Go and Python", "Go") is True
    assert mentions_term("Chose Google Cloud", "Go") is False
    assert mentions_term("used C++ daily", "C++") is True
    assert mentions_term("used C daily", "C++") is False
    assert mentions_term("Trained models with torch", "PyTorch") is True  # alias
    assert mentions_term("Kubernetes-based rollout", "Kubernetes") is True


def test_novel_terms_only_flags_names_the_profile_doesnt_hold() -> None:
    allowed = {"flask", "xgboost"}

    assert novel_terms("Built it with Flask and XGBoost.", allowed) == []
    assert novel_terms("Built it with Flask and Django.", allowed) == ["Django"]


def _skills(*names: str) -> list[SkillItem]:
    return [SkillItem(name=n, level="advanced", category=None) for n in names]


def test_reorder_moves_requested_skills_to_the_front_keeping_the_rest_stable() -> None:
    skills = _skills("Linux", "Git", "Python", "Docker", "SQL")

    order = reorder_skills(skills, required=["python"], preferred=["Docker"])

    assert order == ["Python", "Docker", "Linux", "Git", "SQL"]


def test_reorder_is_none_when_nothing_would_change() -> None:
    assert reorder_skills(_skills("Python", "Docker", "Git"), ["Python"], ["Docker"]) is None
    assert reorder_skills(_skills("Git", "Linux"), ["Kubernetes"], []) is None


def test_reorder_matches_aliases_and_only_permutes() -> None:
    skills = _skills("Linux", "PyTorch")

    order = reorder_skills(skills, required=["torch"], preferred=[])

    assert order == ["PyTorch", "Linux"]
    assert sorted(order or []) == sorted(s.name for s in skills)  # nothing added or dropped


def test_gaps_separate_unevidenced_from_absent_and_skip_covered_skills() -> None:
    base = ResumeBase(
        name=None,
        headline=None,
        location=None,
        summary=None,
        skills=_skills("Python"),
        unevidenced_skills=["Docker"],
    )

    gaps = find_gaps(base, required=["Python", "Docker", "Rust"], preferred=["Kubernetes", "rust"])

    assert gaps == [
        {
            "skill": "Docker",
            "kind": "required",
            "reason": "it's in your profile, but with no evidence recorded",
        },
        {"skill": "Rust", "kind": "required", "reason": "it isn't in your profile"},
        {"skill": "Kubernetes", "kind": "preferred", "reason": "it isn't in your profile"},
    ]
