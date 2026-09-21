"""Sentence-level fact-checking for cover letters — pure code, no I/O.

The LLM writes a letter as sentences, each declaring what supports it. Nothing it says is
trusted: every sentence is checked here, and a sentence that can't be backed is dropped (with
its reason) rather than shown as fact. Supports are one of:

- ``profile_experience`` (ref ``exp:<id>``): a role on the user's profile,
- ``profile_skill`` (ref = skill name): a skill the user has *recorded evidence* for,
- ``profile_summary`` (ref ``summary``): the user's own summary,
- ``posting_quote`` (ref = an excerpt): text that must appear verbatim in the job posting.

Two kinds of sentence: ``fact`` (says something about the user or the role — needs support) and
``framing`` (greeting, transition, sign-off — must contain no facts at all: no numbers, no
skills, no names it wasn't given).

The rule that matters most: **a skill is only ever claimed if the user holds it.** A skill the
posting asks for but the profile lacks can't appear in the letter in any form — otherwise "I have
Kubernetes experience", citing the posting's own "Kubernetes experience", would pass a
quote check while being false about the user. The same heuristics (and the same reasoning about
being conservative) as app.career.resume_verify apply.
"""

from dataclasses import dataclass
from typing import Any

from app.career.matching import normalize_skill
from app.career.resume_base import ResumeBase
from app.career.resume_verify import mentions_term, novel_terms, numbers_in, words_in
from app.research.verify import verify_citation_excerpt

MAX_FACT_CHARS = 320
MAX_FRAMING_CHARS = 200

SUPPORT_TYPES = ("profile_experience", "profile_skill", "profile_summary", "posting_quote")

# Words any letter needs that read as "names" to the heuristics ("I" mid-sentence).
_BASELINE_WORDS = {"i"}


@dataclass
class VerifyContext:
    base: ResumeBase
    posting_text: str
    job_title: str | None
    company: str | None
    # Skills to police: the posting's, plus every skill the user has (evidenced or not).
    watch_terms: list[str]


@dataclass
class _Resolved:
    clean: dict[str, str]  # what's stored: {type, ref, label, excerpt}
    source_text: str  # what the sentence is checked against
    is_profile: bool
    # For a role: the skills whose recorded evidence points at it; for a skill: itself.
    entitled_skills: list[str]


def _resolve_support(raw: Any, ctx: VerifyContext) -> tuple[_Resolved | None, str | None]:
    if not isinstance(raw, dict):
        return None, "a support was malformed"
    kind = str(raw.get("type") or "")
    ref = str(raw.get("ref") or "").strip()
    if kind not in SUPPORT_TYPES:
        return None, f"it cited an unknown kind of support ({kind or 'none'})"

    if kind == "profile_experience":
        exp = next((e for e in ctx.base.experiences if f"exp:{e.id}" == ref), None)
        if exp is None:
            return None, "it cited a role that isn't on your profile"
        label = f"{exp.title} — {exp.company}"
        text = f"{exp.title} {exp.company} {exp.location or ''} {exp.description or ''}"
        return (
            _Resolved(
                {"type": kind, "ref": ref, "label": label, "excerpt": exp.description or ""},
                text,
                True,
                list(exp.linked_skills),
            ),
            None,
        )

    if kind == "profile_skill":
        skill = next(
            (s for s in ctx.base.skills if normalize_skill(s.name) == normalize_skill(ref)), None
        )
        if skill is None:
            return None, f"it cited the skill '{ref}', which has no recorded evidence"
        return (
            _Resolved(
                {"type": kind, "ref": skill.name, "label": skill.name, "excerpt": skill.evidence},
                f"{skill.name} {skill.evidence}",
                True,
                [skill.name],
            ),
            None,
        )

    if kind == "profile_summary":
        if not (ctx.base.summary or "").strip():
            return None, "it cited a summary your profile doesn't have"
        summary = ctx.base.summary or ""
        return (
            _Resolved(
                {"type": kind, "ref": "summary", "label": "Your summary", "excerpt": summary},
                summary,
                True,
                [],
            ),
            None,
        )

    # posting_quote
    if not ref or not verify_citation_excerpt(ref, ctx.posting_text):
        return None, "it quoted the posting, but that text isn't in the posting"
    clean = {"type": kind, "ref": ref, "label": "The posting", "excerpt": ref}
    return _Resolved(clean, ref, False, []), None


def verify_sentence(raw: Any, ctx: VerifyContext) -> tuple[dict[str, Any] | None, str | None]:
    """Returns (clean sentence, None) if it may be shown, or (None, why it was discarded)."""
    if not isinstance(raw, dict):
        return None, "the sentence was malformed"
    text = str(raw.get("text") or "").strip()
    if not text:
        return None, "the sentence was empty"
    kind = "framing" if raw.get("kind") == "framing" else "fact"

    company_title_words = words_in(f"{ctx.company or ''} {ctx.job_title or ''}")
    name_words = words_in(ctx.base.name or "")
    numbers_ok = numbers_in(f"{ctx.company or ''} {ctx.job_title or ''}")

    if kind == "framing":
        if len(text) > MAX_FRAMING_CHARS:
            return None, "a transition sentence ran long, where unsupported detail hides"
        if numbers_in(text):
            return None, "a sentence with no cited support contains a number"
        for term in ctx.watch_terms:
            if mentions_term(text, term):
                return None, f"a sentence with no cited support mentions '{term}'"
        novel = novel_terms(text, _BASELINE_WORDS | company_title_words | name_words)
        if novel:
            return None, f"a sentence with no cited support introduces {_quote_all(novel)}"
        return {"text": text, "kind": "framing", "supports": []}, None

    if len(text) > MAX_FACT_CHARS:
        return None, "it is too long to verify sentence by sentence"

    raw_supports = raw.get("supports")
    if not isinstance(raw_supports, list) or not raw_supports:
        return None, "it states a fact but cites nothing to support it"

    resolved: list[_Resolved] = []
    for raw_support in raw_supports:
        support, problem = _resolve_support(raw_support, ctx)
        if support is None:
            return None, problem
        resolved.append(support)

    profile_text = " ".join(r.source_text for r in resolved if r.is_profile)
    quote_text = " ".join(r.source_text for r in resolved if not r.is_profile)

    # A number about the user must come from the user's own profile. A number from a cited
    # posting quote is deliberately not enough: "I have 5 years", citing the posting's
    # "5+ years required", would be false.
    added = sorted(numbers_in(text) - numbers_in(profile_text) - numbers_ok)
    if added:
        return None, f"it states number(s) not in the profile item it cites: {', '.join(added)}"

    entitled = {normalize_skill(s) for r in resolved for s in r.entitled_skills}
    for term in ctx.watch_terms:
        if not mentions_term(text, term):
            continue
        if normalize_skill(term) in entitled or mentions_term(profile_text, term):
            continue
        return None, f"it mentions '{term}', which your profile doesn't support"

    allowed_words = (
        _BASELINE_WORDS
        | words_in(profile_text)
        | words_in(quote_text)
        | company_title_words
        | name_words
        | words_in(" ".join(r.clean["label"] for r in resolved))
    )
    novel = novel_terms(text, allowed_words)
    if novel:
        return None, f"it introduces {_quote_all(novel)}, found in nothing it cites"

    return {"text": text, "kind": "fact", "supports": [r.clean for r in resolved]}, None


def _quote_all(words: list[str]) -> str:
    return ", ".join(repr(w) for w in words)
