from app.research.dedupe import (
    content_hash,
    cosine_similarity,
    find_semantic_duplicates,
    normalize_url,
)


def test_normalize_url_strips_tracking_params_and_www() -> None:
    url = "https://WWW.Example.com/jobs/123/?utm_source=newsletter&utm_campaign=x&ref=abc"
    assert normalize_url(url) == "https://example.com/jobs/123"


def test_normalize_url_keeps_meaningful_query_params() -> None:
    url = "https://example.com/search?id=42"
    assert normalize_url(url) == "https://example.com/search?id=42"


def test_normalize_url_is_stable_for_equivalent_urls() -> None:
    a = normalize_url("https://example.com/jobs/123/")
    b = normalize_url("http://www.example.com/jobs/123?utm_source=x")
    assert a == b


def test_content_hash_ignores_whitespace_and_case_differences() -> None:
    a = content_hash("Hello   World")
    b = content_hash("hello world")
    assert a == b


def test_content_hash_differs_for_different_content() -> None:
    assert content_hash("Hello World") != content_hash("Goodbye World")


def test_cosine_similarity_identical_vectors_is_one() -> None:
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == 1.0


def test_cosine_similarity_orthogonal_vectors_is_zero() -> None:
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0


def test_find_semantic_duplicates_collapses_near_identical_embeddings() -> None:
    embeddings = {
        "a": [1.0, 0.0],
        "b": [0.999, 0.001],  # near-duplicate of "a"
        "c": [0.0, 1.0],  # unrelated
    }
    duplicates = find_semantic_duplicates(embeddings, threshold=0.97)
    assert duplicates == {"b": "a"}


def test_find_semantic_duplicates_empty_when_all_distinct() -> None:
    embeddings = {"a": [1.0, 0.0], "b": [0.0, 1.0]}
    assert find_semantic_duplicates(embeddings) == {}
