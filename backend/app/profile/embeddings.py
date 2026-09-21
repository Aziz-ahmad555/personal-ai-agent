import uuid

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from voyageai.client_async import AsyncClient

from app.config import get_settings
from app.logging import get_logger
from app.profile.models import ProfileEmbedding

logger = get_logger(__name__)

_client: AsyncClient | None = None


def _get_client() -> AsyncClient | None:
    global _client
    settings = get_settings()
    if not settings.voyage_api_key:
        return None
    if _client is None:
        _client = AsyncClient(api_key=settings.voyage_api_key)
    return _client


async def embed_texts(
    texts: list[str], *, input_type: str = "document"
) -> list[list[float]] | None:
    """Returns one embedding vector per input text, or None if embeddings are unavailable —
    either disabled (no VOYAGE_API_KEY set) or the API call itself failed (rate limit,
    network error, outage). Callers indexing content (profile fields, research chunks) must
    treat None as "skipped" and never fabricate a vector — embeddings are supplementary
    there, never load-bearing, so a Voyage-side hiccup must degrade the embedding step
    alone, not crash the caller's whole operation. Search is the one caller where this
    return value IS load-bearing (see embed_query below): without a query vector there is
    nothing to search against, and that caller must fail the request clearly rather than
    silently return zero results.

    `input_type` should be "document" when embedding content to be indexed and "query" when
    embedding a search query — Voyage's retrieval models are trained asymmetrically and
    tag which side of the pair they're embedding for better match quality."""
    if not texts:
        return []

    client = _get_client()
    if client is None:
        logger.warning("embeddings_skipped_no_api_key")
        return None

    settings = get_settings()
    try:
        result = await client.embed(texts, model=settings.voyage_model, input_type=input_type)
    except Exception as exc:
        logger.warning("embeddings_skipped_api_error", error=str(exc))
        return None
    return [[float(value) for value in vector] for vector in result.embeddings]


async def embed_query(text: str) -> list[float] | None:
    """Embeds a single search query with Voyage's "query" input type (see embed_texts).
    Returns None under the same conditions embed_texts does — callers must treat that as
    "search is unavailable right now", not "no results"."""
    vectors = await embed_texts([text], input_type="query")
    if not vectors:
        return None
    return vectors[0]


async def sync_embedding(
    db: AsyncSession,
    *,
    profile_id: uuid.UUID,
    owner_type: str,
    owner_id: uuid.UUID,
    text: str | None,
) -> None:
    """Replaces whatever embedding(s) exist for (owner_type, owner_id) with one for `text`.
    Pass an empty/None text to just clear the embedding (e.g. the field was blanked out)."""
    await db.execute(
        delete(ProfileEmbedding).where(
            ProfileEmbedding.owner_type == owner_type, ProfileEmbedding.owner_id == owner_id
        )
    )

    if not text or not text.strip():
        return

    vectors = await embed_texts([text])
    if vectors is None:
        return

    db.add(
        ProfileEmbedding(
            profile_id=profile_id,
            owner_type=owner_type,
            owner_id=owner_id,
            chunk_text=text,
            embedding=vectors[0],
        )
    )


async def delete_embedding(db: AsyncSession, *, owner_type: str, owner_id: uuid.UUID) -> None:
    await db.execute(
        delete(ProfileEmbedding).where(
            ProfileEmbedding.owner_type == owner_type, ProfileEmbedding.owner_id == owner_id
        )
    )
