from app.research.verify import verify_citation_excerpt, verify_source


def test_verify_source_passes_for_substantive_200_response() -> None:
    passed, reason = verify_source(http_status=200, content="x" * 250, fetch_error=None)
    assert passed is True
    assert reason is None


def test_verify_source_fails_for_non_200() -> None:
    passed, reason = verify_source(http_status=404, content=None, fetch_error="http_404")
    assert passed is False
    assert reason == "http_404"


def test_verify_source_fails_for_empty_or_parked_page() -> None:
    passed, reason = verify_source(http_status=200, content="too short", fetch_error=None)
    assert passed is False
    assert reason == "empty_or_parked_page"


def test_verify_source_fails_when_fetch_error_present_even_with_200() -> None:
    passed, reason = verify_source(
        http_status=200, content="x" * 250, fetch_error="robots_disallowed"
    )
    assert passed is False
    assert reason == "robots_disallowed"


def test_verify_citation_excerpt_matches_verbatim_substring() -> None:
    source = "Acme Corp requires 5 years of PyTorch experience for this role."
    assert verify_citation_excerpt("5 years of PyTorch experience", source) is True


def test_verify_citation_excerpt_ignores_whitespace_and_case() -> None:
    source = "Acme Corp requires  5  years\nof PyTorch experience."
    assert verify_citation_excerpt("5 YEARS OF PYTORCH EXPERIENCE", source) is True


def test_verify_citation_excerpt_rejects_text_not_present() -> None:
    source = "Acme Corp requires 5 years of PyTorch experience."
    assert verify_citation_excerpt("10 years of TensorFlow experience", source) is False


def test_verify_citation_excerpt_rejects_empty_excerpt() -> None:
    assert verify_citation_excerpt("", "some content") is False
