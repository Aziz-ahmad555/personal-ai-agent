import types
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import User
from app.profile import embeddings
from app.profile.models import Profile, ProfileEmbedding


async def test_get_client_returns_none_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(embeddings, "_client", None)
    monkeypatch.setattr(
        embeddings, "get_settings", lambda: types.SimpleNamespace(voyage_api_key=None)
    )

    assert embeddings._get_client() is None


async def test_sync_embedding_skips_storage_when_embeddings_disabled(
    monkeypatch: pytest.MonkeyPatch, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async def _disabled_embed(texts: list[str]) -> list[list[float]] | None:
        return None

    monkeypatch.setattr(embeddings, "embed_texts", _disabled_embed)

    async with session_factory() as db:
        user = User(email="embed-skip@example.com", hashed_password="x")
        db.add(user)
        await db.flush()
        profile = Profile(user_id=user.id)
        db.add(profile)
        await db.flush()

        await embeddings.sync_embedding(
            db, profile_id=profile.id, owner_type="bio", owner_id=profile.id, text="hello world"
        )
        await db.commit()

        result = await db.execute(select(ProfileEmbedding))
        assert result.first() is None


async def test_profile_update_stores_a_bio_embedding(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """End-to-end through the API: with embeddings "enabled" (the autouse fake), saving a
    bio actually produces a queryable ProfileEmbedding row, not just a 200 response."""
    response = await client.put(
        "/profile",
        headers=auth_headers,
        json={"headline": "ML Engineer", "summary": "Builds things."},
    )
    profile_id = uuid.UUID(response.json()["id"])

    async with session_factory() as db:
        result = await db.execute(
            select(ProfileEmbedding).where(
                ProfileEmbedding.owner_type == "bio", ProfileEmbedding.owner_id == profile_id
            )
        )
        embedding = result.scalar_one()
        assert len(embedding.embedding) == 512
        assert "ML Engineer" in embedding.chunk_text
