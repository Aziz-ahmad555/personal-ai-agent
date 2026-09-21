"""Deterministic checks on what the LLM proposes for a tailored resume — pure code, no I/O.

The model may only *rephrase and emphasize* what a profile item already says. These checks
are what enforce that, so a fabricated claim never reaches the user as a suggestion. A proposal
is rejected (with a reason that's shown, not swallowed) if it:

- adds a number that isn't in the source item,
- mentions a skill from the posting (or any of the user's skills) that the item doesn't
  support — for a role, that means the skill's evidence doesn't point at that role,
- introduces a proper-looking term (a tool, product, employer...) found nowhere in what the
  profile holds, or
- balloons in length, which is where invented detail tends to hide.

They're heuristics over text, deliberately conservative: a false rejection costs the user one
suggestion; a false acceptance would put a claim on their resume that they never made. And
every surviving suggestion is still reviewed by the user, change by change.
"""

import re

from app.career.matching import normalize_skill, skill_variants
from app.career.resume_base import ResumeBase, SkillItem

MAX_GROWTH_FACTOR = 1.5
MAX_GROWTH_SLACK_CHARS = 60

_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9+#]*")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")


def _numbers(text: str) -> set[str]:
    return {m.replace(",", "") for m in _NUMBER_RE.findall(text)}


def _words(text: str) -> set[str]:
    return {w.lower() for w in _WORD_RE.findall(text)}


def mentions_term(text: str, term: str) -> bool:
    variants = sorted(skill_variants(term), key=len, reverse=True)
    alternatives = "|".join(re.escape(v) for v in variants)
    pattern = rf"(?<![A-Za-z0-9+#])(?:{alternatives})(?![A-Za-z0-9+#])"
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


def _proper_looking(word: str, is_sentence_start: bool) -> bool:
    if len(word) >= 2 and word.isupper():
        return True  # AWS, SQL, GPU
    if any(c.isupper() for c in word[1:]) or any(c.isdigit() or c in "+#" for c in word):
        return True  # PyTorch, GPT4, C++
    return word[0].isupper() and not is_sentence_start  # a name in mid-sentence: Kubernetes


def novel_terms(new_text: str, allowed_words: set[str]) -> list[str]:
    """Proper-looking words in `new_text` that aren't among the words the profile holds."""
    found: list[str] = []
    for sentence in _SENTENCE_SPLIT_RE.split(new_text):
        for index, word in enumerate(_WORD_RE.findall(sentence)):
            if _proper_looking(word, index == 0) and word.lower() not in allowed_words:
                if word not in found:
                    found.append(word)
    return found


def verify_rewrite(
    *,
    source_text: str,
    new_text: str,
    allowed_words: set[str],
    allowed_skill_norms: set[str],
    watch_terms: list[str],
) -> str | None:
    """Returns why a proposed rewrite must be discarded, or None if it may be shown.

    `allowed_words`: every word this item may legitimately use (its own text plus whatever
    else the profile says it may draw on — see resume_service). `allowed_skill_norms`:
    normalized names of skills this item is *entitled to claim* (evidence-backed and, for a
    role, linked to it). `watch_terms`: skills to police — the posting's and the user's own."""
    new = new_text.strip()
    if not new:
        return "the suggestion was empty"

    if len(new) > len(source_text) * MAX_GROWTH_FACTOR + MAX_GROWTH_SLACK_CHARS:
        return "it is much longer than the original, which is where invented detail hides"

    added_numbers = sorted(_numbers(new) - _numbers(source_text))
    if added_numbers:
        return f"it adds number(s) not in the original: {', '.join(added_numbers)}"

    for term in watch_terms:
        if (
            mentions_term(new, term)
            and not mentions_term(source_text, term)
            and normalize_skill(term) not in allowed_skill_norms
        ):
            return f"it claims '{term}', which your profile doesn't support for this item"

    novel = novel_terms(new, allowed_words | _words(source_text))
    if novel:
        return f"it introduces {', '.join(repr(t) for t in novel)}, found nowhere in your profile"

    return None


def _matches_any(skill_name: str, wanted: list[str]) -> bool:
    return normalize_skill(skill_name) in {normalize_skill(w) for w in wanted}


def reorder_skills(
    skills: list[SkillItem], required: list[str], preferred: list[str]
) -> list[str] | None:
    """Skills the posting asks for first (required, then preferred), the rest in their
    original order. Returns the new order of names, or None if it wouldn't change anything.
    Reordering is a permutation of the user's own evidence-backed skills — it can't add a
    claim, so it needs no LLM."""
    def rank(skill: SkillItem) -> int:
        if _matches_any(skill.name, required):
            return 0
        if _matches_any(skill.name, preferred):
            return 1
        return 2

    ordered = sorted(skills, key=rank)  # sorted() is stable, so ties keep their order
    names = [s.name for s in ordered]
    return names if names != [s.name for s in skills] else None


def find_gaps(
    base: ResumeBase, required: list[str], preferred: list[str]
) -> list[dict[str, str]]:
    """Skills the posting asks for that the profile has no *evidence* for. Reported to the user,
    never written into the resume."""
    evidenced = {normalize_skill(s.name) for s in base.skills}
    unevidenced = {normalize_skill(n) for n in base.unevidenced_skills}
    gaps: list[dict[str, str]] = []
    seen: set[str] = set()
    for kind, names in (("required", required), ("preferred", preferred)):
        for name in names:
            norm = normalize_skill(name)
            if norm in evidenced or norm in seen:
                continue
            seen.add(norm)
            reason = (
                "it's in your profile, but with no evidence recorded"
                if norm in unevidenced
                else "it isn't in your profile"
            )
            gaps.append({"skill": name, "kind": kind, "reason": reason})
    return gaps
