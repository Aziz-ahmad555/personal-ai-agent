"""Chunks and embeds research content into ResearchEmbedding rows, reusing the same Voyage
wrapper Phase 2 built (app.profile.embeddings.embed_texts) rather than standing up a second
API client — it's already generic (provider-level, not Profile-specific), fails closed to
None (never a fabricated vector) when VOYAGE_API_KEY is unset, and every caller here must
treat that None the same way Phase 2 does: skip, log, move on."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.logging import get_logger
from app.profile.embeddings import embed_texts
from app.research.models import ResearchEmbedding

logger = get_logger(__name__)

CHUNK_SIZE = 1500
# Voyage accepts at most this many input texts per request; larger batches are split.
VOYAGE_MAX_BATCH_INPUTS = 128


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE) -> list[str]:
    text = text.strip()
    if not text:
        return []
    return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]


async def embed_and_store_batch(
    db: AsyncSession,
    *,
    query_id: uuid.UUID,
    owner_type: str,
    items: list[tuple[uuid.UUID, str]],
) -> dict[uuid.UUID, list[list[float]]]:
    """Chunks each (owner_id, text), embeds every chunk in as few Voyage requests as possible,
    and stores one ResearchEmbedding row per chunk. Returns the vectors per owner (so a caller
    doing same-call semantic dedup doesn't need a round trip back to the DB). Owners whose
    text is empty, or every owner when embeddings are disabled or unavailable, are simply
    absent from the result — callers must treat that as "skipped", never fabricate a vector."""
    chunked: list[tuple[uuid.UUID, int, str]] = [
        (owner_id, index, chunk)
        for owner_id, text in items
        for index, chunk in enumerate(chunk_text(text))
    ]
    if not chunked:
        return {}

    all_vectors: list[list[float]] = []
    for start in range(0, len(chunked), VOYAGE_MAX_BATCH_INPUTS):
        batch = [chunk for _, _, chunk in chunked[start : start + VOYAGE_MAX_BATCH_INPUTS]]
        vectors = await embed_texts(batch)
        if vectors is None:
            # embed_texts() already logged the specific reason (no key vs. API error).
            logger.warning("research_embedding_skipped", owner_type=owner_type, count=len(chunked))
            return {}
        all_vectors.extend(vectors)

    by_owner: dict[uuid.UUID, list[list[float]]] = {}
    for (owner_id, index, chunk), vector in zip(chunked, all_vectors, strict=True):
        db.add(
            ResearchEmbedding(
                query_id=query_id,
                owner_type=owner_type,
                owner_id=owner_id,
                chunk_index=index,
                chunk_text=chunk,
                embedding=vector,
            )
        )
        by_owner.setdefault(owner_id, []).append(vector)
    return by_owner
