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


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE) -> list[str]:
    text = text.strip()
    if not text:
        return []
    return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]


async def embed_and_store(
    db: AsyncSession,
    *,
    query_id: uuid.UUID,
    owner_type: str,
    owner_id: uuid.UUID,
    text: str,
) -> list[list[float]] | None:
    """Chunks `text`, embeds each chunk, and stores one ResearchEmbedding row per chunk.
    Returns the embedding vectors (so a caller doing same-call semantic dedup doesn't need
    a round trip back to the DB), or None if embeddings are disabled — callers must treat
    that as "skipped", falling back to exact-hash dedup only, never fabricate a vector."""
    chunks = chunk_text(text)
    if not chunks:
        return None

    vectors = await embed_texts(chunks)
    if vectors is None:
        # embed_texts() already logged the specific reason (no key vs. API error) — this
        # just ties that skip to the research row it would have embedded, for audit.
        logger.warning("research_embedding_skipped", owner_type=owner_type, owner_id=str(owner_id))
        return None

    for index, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True)):
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

    return vectors
