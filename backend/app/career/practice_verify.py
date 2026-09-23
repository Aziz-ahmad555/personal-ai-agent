"""Grounding checks for interview practice — pure code, no I/O.

Two checks live here, one per LLM step in app.career.practice_llm:

- `resolve_question_ref` / `verify_question`: the model proposes a question grounded in a
  posting requirement or a profile experience/skill, by name/id. Nothing it says is trusted —
  the real quote or evidence text is looked up here from the already-verified pool (the match's
  quote-checked requirements, or the profile's recorded evidence), never reproduced by the model
  itself. This is stricter than app.career.cover_verify's `posting_quote` support, where the
  model reproduces its own quote for us to check: here it never gets the chance to mangle one.
  A reference that doesn't resolve to anything real means the question is dropped.

- `verify_feedback_item`: the model writes feedback on the user's answer. Its rationale is
  checked against only the question's own grounding text and the user's own answer — the same
  "don't let a fact ride in unchecked" discipline as app.career.cover_verify, applied to
  (grounding, answer) instead of (posting, profile).
"""

from dataclasses import dataclass
from typing import Any

from app.career.matching import normalize_skill
from app.career.resume_base import ResumeBase
from app.career.resume_verify import mentions_term, novel_terms, numbers_in, words_in

MAX_RATIONALE_CHARS = 400
QUESTION_CATEGORIES = ("technical", "behavioral", "situational")
REF_TYPES = ("posting_requirement", "profile_experience", "profile_skill")
VERDICTS = ("addressed", "partially_addressed", "missed", "unclear")


@dataclass
class ResolvedRef:
    ref_type: str
    ref_name: str  # human-readable label
    ref_excerpt: str  # the quote (posting) or evidence text (profile)


def resolve_question_ref(
    raw: Any, *, requirements: list[dict[str, Any]], base: ResumeBase
) -> tuple[ResolvedRef | None, str | None]:
    """Returns (resolved, None), or (None, why it couldn't be grounded)."""
    if not isinstance(raw, dict):
        return None, "the question was malformed"
    ref_type = str(raw.get("ref_type") or "")
    ref = str(raw.get("ref") or "").strip()
    if not ref:
        return None, "it cited nothing to ground the question in"

    if ref_type == "posting_requirement":
        match = next(
            (r for r in requirements if normalize_skill(r["name"]) == normalize_skill(ref)), None
        )
        if match is None:
            return None, f"it referenced '{ref}', which isn't a requirement from this posting"
        return ResolvedRef("posting_requirement", match["name"], match["quote"]), None

    if ref_type == "profile_experience":
        exp = next((e for e in base.experiences if f"exp:{e.id}" == ref), None)
        if exp is None:
            return None, "it referenced a role that isn't on your profile"
        label = f"{exp.title} — {exp.company}"
        return ResolvedRef("profile_experience", label, exp.description or ""), None

    if ref_type == "profile_skill":
        skill = next(
            (s for s in base.skills if normalize_skill(s.name) == normalize_skill(ref)), None
        )
        if skill is None:
            return None, f"it referenced the skill '{ref}', which has no recorded evidence"
        return ResolvedRef("profile_skill", skill.name, skill.evidence), None

    return None, f"it cited an unknown kind of grounding ({ref_type or 'none'})"


def verify_question(
    raw: Any, *, requirements: list[dict[str, Any]], base: ResumeBase
) -> tuple[dict[str, Any] | None, str | None]:
    """Returns (clean question, None) if it may be shown, or (None, why it was discarded)."""
    if not isinstance(raw, dict):
        return None, "the question was malformed"
    text = str(raw.get("text") or "").strip()
    if not text:
        return None, "the question was empty"
    category = raw.get("category")
    if category not in QUESTION_CATEGORIES:
        category = "behavioral"

    resolved, reason = resolve_question_ref(raw, requirements=requirements, base=base)
    if resolved is None:
        return None, reason or "it could not be grounded"

    return {
        "text": text,
        "category": category,
        "ref_type": resolved.ref_type,
        "ref_name": resolved.ref_name,
        "ref_excerpt": resolved.ref_excerpt,
    }, None


def verify_feedback_item(
    raw: Any, *, ref_type: str, ref_name: str, ref_excerpt: str, answer_text: str
) -> tuple[str, str] | None:
    """Returns (verdict, rationale) if the feedback may be shown, or None if it must fall back to
    a fixed, honest message instead of a guess. The rationale may only draw on the question's own
    grounding excerpt and the candidate's own answer — nothing else counts as known.

    That vocabulary check alone isn't enough for a *positive* verdict, though: `ref_excerpt`
    always mentions the thing being asked about, regardless of what the candidate actually
    said, so crediting "addressed"/"partially_addressed" on vocabulary alone can credit a claim
    the answer never made (caught by a red-team test — see test_redteam_injection.py). For a
    `posting_requirement` question specifically (a skill/requirement name, where an honest
    answer repeating it is a reasonable bar), a positive verdict that mentions the term must
    have that term actually present in the candidate's own answer. Not extended to
    `profile_experience`/`profile_skill` refs: a good answer naturally won't repeat a role's
    "Title — Company" label or a skill's own name verbatim, so the same bar there would punish
    honest answers, not dishonest feedback."""
    if not isinstance(raw, dict):
        return None
    verdict = raw.get("verdict")
    if verdict not in VERDICTS:
        return None
    rationale = str(raw.get("rationale") or "").strip()
    if not rationale or len(rationale) > MAX_RATIONALE_CHARS:
        return None

    known_text = f"{ref_excerpt} {answer_text}"
    if numbers_in(rationale) - numbers_in(known_text):
        return None
    if novel_terms(rationale, words_in(known_text)):
        return None

    if (
        ref_type == "posting_requirement"
        and verdict in ("addressed", "partially_addressed")
        and mentions_term(rationale, ref_name)
        and not mentions_term(answer_text, ref_name)
    ):
        return None

    return str(verdict), rationale
