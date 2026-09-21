"""Deduplication has two layers:

1. Exact — normalize_url() strips tracking params so two links to the same page collapse
   to one ResearchSource row (enforced by the unique constraint on normalized_url);
   content_hash() catches byte-identical content served from different URLs.
2. Semantic — cosine_similarity() over Voyage embeddings catches near-duplicate content
   exact hashing misses (e.g. a press release syndicated with minor formatting changes
   across outlets), so it isn't miscounted as independent corroboration.
"""

import hashlib
import math
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

_TRACKING_PARAM_PREFIXES = ("utm_", "fbclid", "gclid", "gclsrc", "msclkid", "mc_", "ref", "ref_")

SEMANTIC_DUPLICATE_THRESHOLD = 0.97


def normalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    scheme = "https" if parsed.scheme in ("http", "https") else parsed.scheme
    netloc = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path.rstrip("/") or "/"

    kept_query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not any(key.lower().startswith(prefix) for prefix in _TRACKING_PARAM_PREFIXES)
    ]
    kept_query.sort()

    return urlunparse((scheme, netloc, path, "", urlencode(kept_query), ""))


def content_hash(content: str) -> str:
    normalized = re.sub(r"\s+", " ", content).strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def find_semantic_duplicates(
    embeddings: dict[str, list[float]], threshold: float = SEMANTIC_DUPLICATE_THRESHOLD
) -> dict[str, str]:
    """Given {source_id: embedding} for one query's newly-collected sources, returns
    {duplicate_source_id: canonical_source_id} for any pair whose cosine similarity meets
    the threshold. The first-seen id in iteration order is kept as canonical."""
    ids = list(embeddings.keys())
    duplicate_of: dict[str, str] = {}
    for i, id_a in enumerate(ids):
        if id_a in duplicate_of:
            continue
        for id_b in ids[i + 1 :]:
            if id_b in duplicate_of:
                continue
            if cosine_similarity(embeddings[id_a], embeddings[id_b]) >= threshold:
                duplicate_of[id_b] = id_a
    return duplicate_of
