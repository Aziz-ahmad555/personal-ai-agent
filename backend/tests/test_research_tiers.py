from app.research.tiers import classify_domain


def test_unknown_domain_defaults_to_lowest_trust() -> None:
    tier, rationale = classify_domain("some-random-blog.example")
    assert tier == "unknown"
    assert "lowest trust" in rationale


def test_government_suffix_classified_as_government() -> None:
    tier, _ = classify_domain("uscis.gov")
    assert tier == "government"


def test_curated_docs_domain_classified_as_docs() -> None:
    tier, _ = classify_domain("docs.python.org")
    assert tier == "docs"


def test_curated_reputable_secondary_domain() -> None:
    tier, _ = classify_domain("www.reuters.com")
    assert tier == "reputable_secondary"


def test_forum_domain_classified_as_anecdotal() -> None:
    tier, rationale = classify_domain("www.reddit.com")
    assert tier == "forum_anecdotal"
    assert "anecdote only" in rationale


def test_employer_domain_classified_as_official_only_when_confirmed() -> None:
    tier, _ = classify_domain("careers.acme.com", employer_domains={"acme.com"})
    assert tier == "official"

    # Without a confirmed employer domain, the same page is not automatically "official".
    tier_unconfirmed, _ = classify_domain("careers.acme.com")
    assert tier_unconfirmed == "unknown"


def test_lookalike_domain_does_not_match_curated_allowlist() -> None:
    tier, _ = classify_domain("reuters.com.evil-mirror.net")
    assert tier == "unknown"
