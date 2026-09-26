"""Cover-letter fact-checking. Each case is a way an LLM might "helpfully" embellish a letter;
every one must be caught, while an honest, cited sentence must pass."""

from app.career.cover_render import render_letter
from app.career.cover_verify import VerifyContext, verify_sentence
from app.career.resume_base import ExperienceItem, ResumeBase, SkillItem

POSTING = (
    "Senior Software Engineer at Acme. Requirements: 5+ years experience with Python or Go, "
    "Kubernetes experience, distributed systems knowledge."
)
VAULTIC = (
    "Building a fraud detection web application using Flask, SQLAlchemy, XGBoost, and "
    "Isolation Forest, including a JWT-authenticated API layer."
)


def _ctx(**overrides) -> VerifyContext:  # type: ignore[no-untyped-def]
    base = ResumeBase(
        name="Aziz Ahmad",
        headline="ML Engineer",
        location=None,
        summary="Engineer who builds ML systems and APIs.",
        experiences=[
            ExperienceItem(
                "e1", "University", "Vaultic", None, "2026-03-01", None, VAULTIC, ["Flask"]
            ),
            ExperienceItem(
                "e2",
                "Individual",
                "Batch Tool",
                None,
                "2025-01-01",
                "2025-06-01",
                "Cut nightly runtime from 12 hours to 3 hours.",
                [],
            ),
        ],
        skills=[
            SkillItem("Flask", "advanced", None, "Built the Vaultic API in Flask."),
            SkillItem("FastAPI", "advanced", None, "Wrote a FastAPI service for the agent."),
        ],
        unevidenced_skills=["Docker"],
    )
    params = {
        "base": base,
        "posting_text": POSTING,
        "job_title": "Senior Software Engineer",
        "company": "Acme",
        "watch_terms": [
            "Python",
            "Go",
            "Kubernetes",
            "Distributed systems",
            "Flask",
            "FastAPI",
            "Docker",
        ],
        **overrides,
    }
    return VerifyContext(**params)


def _fact(text: str, *supports: dict) -> dict:
    return {"text": text, "kind": "fact", "supports": list(supports)}


EXP1 = {"type": "profile_experience", "ref": "exp:e1"}
EXP2 = {"type": "profile_experience", "ref": "exp:e2"}
SKILL_FASTAPI = {"type": "profile_skill", "ref": "FastAPI"}
QUOTE_ROLE = {"type": "posting_quote", "ref": "Senior Software Engineer at Acme"}
QUOTE_K8S = {"type": "posting_quote", "ref": "Kubernetes experience"}


def _reason(raw: dict) -> str | None:
    clean, reason = verify_sentence(raw, _ctx())
    assert (clean is None) == (reason is not None)
    return reason


def test_an_honest_cited_sentence_passes_and_carries_its_evidence() -> None:
    clean, reason = verify_sentence(
        _fact("At Vaultic I built a fraud detection application using Flask and XGBoost.", EXP1),
        _ctx(),
    )

    assert reason is None
    assert clean is not None
    assert clean["kind"] == "fact"
    assert clean["supports"] == [
        {
            "type": "profile_experience",
            "ref": "exp:e1",
            "label": "Vaultic — University",
            "excerpt": VAULTIC,
        }
    ]


def test_a_fact_with_no_support_is_rejected() -> None:
    assert "cites nothing" in (_reason(_fact("I am an excellent engineer.")) or "")


def test_citing_a_role_that_does_not_exist_is_rejected() -> None:
    reason = _reason(_fact("I built things.", {"type": "profile_experience", "ref": "exp:nope"}))

    assert reason is not None
    assert "isn't on your profile" in reason


def test_citing_a_skill_with_no_recorded_evidence_is_rejected() -> None:
    reason = _reason(_fact("I know Docker well.", {"type": "profile_skill", "ref": "Docker"}))

    assert reason is not None
    assert "no recorded evidence" in reason


def test_a_fabricated_posting_quote_is_rejected() -> None:
    reason = _reason(
        _fact(
            "Acme values bold engineers.",
            {"type": "posting_quote", "ref": "we value bold engineers"},
        )
    )

    assert reason is not None
    assert "isn't in the posting" in reason


def test_a_real_posting_quote_supports_a_sentence_about_the_role() -> None:
    clean, reason = verify_sentence(
        _fact("I am applying for the Senior Software Engineer role at Acme.", QUOTE_ROLE), _ctx()
    )

    assert reason is None
    assert clean is not None


def test_claiming_a_skill_the_user_lacks_is_rejected_even_when_the_posting_says_it() -> None:
    # The dangerous one: it quotes the posting accurately, but the claim is about the user.
    reason = _reason(_fact("I have Kubernetes experience.", QUOTE_K8S))

    assert reason is not None
    assert "'Kubernetes'" in reason


def test_a_number_from_a_posting_quote_cannot_become_a_claim_about_the_user() -> None:
    quote = {"type": "posting_quote", "ref": "5+ years experience with Python or Go"}

    reason = _reason(_fact("I have 5 years of experience.", quote))

    assert reason is not None
    assert "number(s)" in reason


def test_numbers_from_the_cited_profile_item_are_fine_but_invented_ones_are_not() -> None:
    assert _reason(_fact("I cut nightly runtime from 12 hours to 3 hours.", EXP2)) is None

    reason = _reason(_fact("I cut nightly runtime from 12 hours to 2 hours.", EXP2))
    assert reason is not None
    assert "2" in reason


def test_a_skill_is_claimable_when_evidence_links_it_to_the_cited_role() -> None:
    # Flask is linked to Vaultic and appears in its description.
    assert _reason(_fact("I built the Vaultic API in Flask.", EXP1)) is None


def test_an_evidenced_skill_not_tied_to_the_cited_role_needs_its_own_citation() -> None:
    sentence = "At Vaultic I also wrote FastAPI services."

    assert "'FastAPI'" in (_reason(_fact(sentence, EXP1)) or "")
    assert _reason(_fact(sentence, EXP1, SKILL_FASTAPI)) is None


def test_a_skill_asserted_without_evidence_cannot_be_claimed_via_a_role() -> None:
    reason = _reason(_fact("At Vaultic I deployed everything with Docker.", EXP1))

    assert reason is not None
    assert "'Docker'" in reason


def test_an_invented_tool_is_caught_even_when_nobody_asked_for_it() -> None:
    reason = _reason(_fact("At Vaultic I provisioned infrastructure with Terraform.", EXP1))

    assert reason is not None
    assert "Terraform" in reason


def test_a_plain_framing_sentence_passes_with_no_supports() -> None:
    clean, reason = verify_sentence(
        {"text": "Thank you for considering my application.", "kind": "framing", "supports": []},
        _ctx(),
    )

    assert reason is None
    assert clean == {
        "text": "Thank you for considering my application.",
        "kind": "framing",
        "supports": [],
    }


def test_framing_must_contain_no_facts() -> None:
    def framing(text: str) -> str | None:
        return _reason({"text": text, "kind": "framing", "supports": []})

    assert "number" in (framing("I look forward to speaking within 2 weeks.") or "")
    assert "'Kubernetes'" in (framing("I would love to work with Kubernetes.") or "")
    assert "Google" in (framing("I have long admired Google.") or "")
    assert framing("I look forward to hearing from you.") is None


def test_framing_may_name_the_company_and_role_it_was_given() -> None:
    assert _reason({"text": "I am excited about Acme.", "kind": "framing", "supports": []}) is None


def test_a_summary_can_be_cited_only_if_the_profile_has_one() -> None:
    summary = {"type": "profile_summary", "ref": "summary"}

    assert _reason(_fact("I build ML systems and APIs.", summary)) is None

    base = _ctx().base
    base.summary = None
    clean, reason = verify_sentence(_fact("I build ML systems.", summary), _ctx(base=base))
    assert clean is None
    assert "summary your profile doesn't have" in (reason or "")


def test_malformed_and_oversized_input_is_rejected_not_crashed_on() -> None:
    assert _reason("not a dict") == "the sentence was malformed"  # type: ignore[arg-type]
    assert _reason({"text": "   ", "kind": "fact", "supports": []}) == "the sentence was empty"
    assert "unknown kind" in (_reason(_fact("x y.", {"type": "magic", "ref": "?"})) or "")
    assert "too long" in (_reason(_fact("I built it. " * 40, EXP1)) or "")


def test_a_missing_kind_is_treated_as_a_fact_that_needs_support() -> None:
    assert "cites nothing" in (_reason({"text": "I am great."}) or "")


def test_render_includes_only_what_is_given_and_never_invents_a_recipient() -> None:
    text = render_letter("Aziz Ahmad", ["First paragraph.", "  Second paragraph.  "])

    assert text == (
        "Dear Hiring Team,\n\nFirst paragraph.\n\nSecond paragraph.\n\nSincerely,\nAziz Ahmad\n"
    )
    assert render_letter(None, ["Only paragraph."]).endswith("Sincerely,\n")
    assert render_letter("Aziz Ahmad", []) == ""
    assert render_letter("Aziz Ahmad", ["   "]) == ""
