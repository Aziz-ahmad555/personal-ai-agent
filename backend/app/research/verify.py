"""Deterministic pass/fail judgments. Two unrelated checks live here:

1. verify_source — is a fetched page substantive enough to trust at all (not a soft-404,
   parked domain, or empty extraction)?
2. verify_citation_excerpt — does a claim's quoted excerpt actually appear in the source
   content it's attributed to? This is the guardrail against a hallucinated or
   misattributed citation from the extraction LLM call.

Both are pure functions on already-fetched data — no network calls — so they're cheap to
unit test in isolation.
"""

import re

MIN_CONTENT_CHARS = 200


def verify_source(
    *, http_status: int | None, content: str | None, fetch_error: str | None
) -> tuple[bool, str | None]:
    if fetch_error is not None:
        return False, fetch_error
    if http_status != 200:
        return False, f"http_{http_status}"
    if not content or len(content.strip()) < MIN_CONTENT_CHARS:
        return False, "empty_or_parked_page"
    return True, None


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def verify_citation_excerpt(excerpt: str, source_content: str) -> bool:
    """Fuzzy substring check: the excerpt (whitespace/case normalized) must appear verbatim
    in the source's stored content. Deliberately strict — this is what stands between a
    claim and it being presented to the user as evidenced fact."""
    if not excerpt or not source_content:
        return False
    return _normalize(excerpt) in _normalize(source_content)
