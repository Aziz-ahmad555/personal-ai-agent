"""Source-tier classification: official > government > docs > reputable_secondary >
forum_anecdotal > unknown. Rule-based on purpose — tier is a trust/policy decision, so it is
never left to LLM judgment (CLAUDE.md: "no LLM for deterministic work ... policy
enforcement — plain code"). An unrecognized domain defaults to "unknown", the *lowest*
trust tier — the classifier fails closed, never fails open to trust.

The allowlists below are a starting curation, not exhaustive. Extend them as the system
encounters legitimate domains it should recognize; never loosen a match to a broad
pattern (e.g. "contains reuters") in a way that could be spoofed by a lookalike domain.
"""

TIER_RANK: dict[str, int] = {
    "official": 5,
    "government": 5,
    "docs": 4,
    "reputable_secondary": 3,
    "forum_anecdotal": 1,
    "unknown": 0,
}

GOVERNMENT_SUFFIXES = (".gov", ".mil", ".gov.uk", ".europa.eu", ".gc.ca")

GOVERNMENT_DOMAINS = {
    "sec.gov",
    "uscis.gov",
    "dol.gov",
    "irs.gov",
    "ftc.gov",
    "sam.gov",
    "courtlistener.com",
}

DOCS_DOMAINS = {
    "docs.python.org",
    "developer.mozilla.org",
    "docs.aws.amazon.com",
    "learn.microsoft.com",
    "docs.microsoft.com",
    "cloud.google.com",
    "kubernetes.io",
    "react.dev",
    "docs.djangoproject.com",
    "fastapi.tiangolo.com",
    "docs.sqlalchemy.org",
    "pytorch.org",
    "www.postgresql.org",
}

REPUTABLE_SECONDARY_DOMAINS = {
    "reuters.com",
    "apnews.com",
    "bloomberg.com",
    "wsj.com",
    "nytimes.com",
    "washingtonpost.com",
    "ft.com",
    "techcrunch.com",
    "theverge.com",
    "arstechnica.com",
    "forbes.com",
    "businessinsider.com",
    "wired.com",
}

FORUM_DOMAINS = {
    "reddit.com",
    "teamblind.com",
    "glassdoor.com",
    "quora.com",
    "news.ycombinator.com",
    "stackoverflow.com",
    "indeed.com",
}


def _registrable_domain(domain: str) -> str:
    """Best-effort second-level+TLD extraction (e.g. "careers.acme.com" -> "acme.com")
    so subdomains of a known/employer domain still match. Not a full public-suffix-list
    implementation — good enough for the common ".something.tld" case this app deals with."""
    parts = domain.lower().split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else domain.lower()


def classify_domain(domain: str, employer_domains: set[str] | None = None) -> tuple[str, str]:
    """Returns (tier, rationale). `employer_domains` are registrable domains the caller has
    already confirmed belong to the specific employer/subject being researched (e.g. from
    a verified careers-page URL) — matching one of those is what earns "official", not any
    self-reported "About us" claim on the page itself."""
    domain = domain.lower()
    registrable = _registrable_domain(domain)

    if employer_domains and registrable in {d.lower() for d in employer_domains}:
        return "official", f"Matches the employer's confirmed domain ({registrable})."

    if domain.endswith(GOVERNMENT_SUFFIXES) or registrable in GOVERNMENT_DOMAINS:
        return "government", f"Government/regulatory domain ({domain})."

    if registrable in DOCS_DOMAINS or domain in DOCS_DOMAINS:
        return "docs", f"Recognized authoritative technical documentation ({domain})."

    if registrable in REPUTABLE_SECONDARY_DOMAINS:
        return "reputable_secondary", f"Recognized outlet with editorial standards ({domain})."

    if registrable in FORUM_DOMAINS:
        return (
            "forum_anecdotal",
            f"User-generated forum/review content ({domain}) — usable as anecdote only, "
            "never as sole support for a claim.",
        )

    return "unknown", f"Domain ({domain}) is not in any curated tier — treated as lowest trust."
