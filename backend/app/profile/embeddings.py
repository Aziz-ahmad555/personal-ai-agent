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


async def embed_texts(texts: list[str]) -> list[list[float]] | None:
    """Returns one embedding vector per input text, or None if embeddings are disabled
    (no VOYAGE_API_KEY set) — callers must treat None as "skipped", never fabricate a vector."""
    if not texts:
        return []

    client = _get_client()
    if client is None:
        logger.warning("embeddings_skipped_no_api_key")
        return None

    settings = get_settings()
    result = await client.embed(texts, model=settings.voyage_model, input_type="document")
    return [[float(value) for value in vector] for vector in result.embeddings]


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
