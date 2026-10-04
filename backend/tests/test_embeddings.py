import types
import uuid

import pytest
import voyageai.error as voyage_errors
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import User
from app.profile import embeddings
from app.profile.models import Preferences, Profile, ProfileEmbedding

# Captured before any test runs, so it's unaffected by the autouse `_fake_embeddings`
# fixture in conftest.py, which replaces `embeddings.embed_texts` wholesale per test —
# tests that need the *real* implementation (e.g. its error handling) call this instead.
_real_embed_texts = embeddings.embed_texts


async def test_voyage_client_is_built_with_a_finite_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The SDK's own default is no timeout at all — a stalled request would hang its caller."""
    built: dict[str, object] = {}

    class _RecordingClient:
        def __init__(self, **kwargs: object) -> None:
            built.update(kwargs)

    monkeypatch.setattr(embeddings, "_client", None)
    monkeypatch.setattr(embeddings, "AsyncClient", _RecordingClient)
    monkeypatch.setattr(
        embeddings, "get_settings", lambda: types.SimpleNamespace(voyage_api_key="test-key")
    )

    embeddings._get_client()

    assert built["timeout"] == embeddings.VOYAGE_TIMEOUT_SECONDS == 30.0


async def test_get_client_returns_none_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(embeddings, "_client", None)
    monkeypatch.setattr(
        embeddings, "get_settings", lambda: types.SimpleNamespace(voyage_api_key=None)
    )

    assert embeddings._get_client() is None


async def test_embed_texts_returns_none_on_api_error_instead_of_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A transient Voyage failure (rate limit, network blip, outage) must degrade to "no
    embeddings" like a missing API key does — never crash the caller's whole operation.
    Regression test for a real rate-limit error that crashed an in-progress research query."""

    class _FakeClient:
        async def embed(self, texts: list[str], *, model: str, input_type: str) -> None:
            raise RuntimeError("429 rate limited")

    monkeypatch.setattr(embeddings, "_get_client", lambda: _FakeClient())

    result = await _real_embed_texts(["some text"])

    assert result is None


async def test_embed_texts_retries_a_transient_error_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(embeddings, "_RETRY_BASE_DELAY_SECONDS", 0.001)
    calls = {"n": 0}

    class _FakeClient:
        async def embed(self, texts: list[str], *, model: str, input_type: str) -> object:
            calls["n"] += 1
            if calls["n"] < 3:
                raise voyage_errors.RateLimitError("rate limited")
            return types.SimpleNamespace(embeddings=[[0.1] * 512 for _ in texts])

    monkeypatch.setattr(embeddings, "_get_client", lambda: _FakeClient())

    result = await _real_embed_texts(["some text"])

    assert result is not None and len(result[0]) == 512
    assert calls["n"] == 3


async def test_embed_texts_gives_up_after_max_attempts_of_a_transient_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(embeddings, "_RETRY_BASE_DELAY_SECONDS", 0.001)
    calls = {"n": 0}

    class _FakeClient:
        async def embed(self, texts: list[str], *, model: str, input_type: str) -> None:
            calls["n"] += 1
            raise voyage_errors.ServiceUnavailableError("down")

    monkeypatch.setattr(embeddings, "_get_client", lambda: _FakeClient())

    result = await _real_embed_texts(["some text"])

    assert result is None
    assert calls["n"] == embeddings._MAX_RETRY_ATTEMPTS


async def test_embed_texts_does_not_retry_a_permanent_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(embeddings, "_RETRY_BASE_DELAY_SECONDS", 0.001)
    calls = {"n": 0}

    class _FakeClient:
        async def embed(self, texts: list[str], *, model: str, input_type: str) -> None:
            calls["n"] += 1
            raise voyage_errors.AuthenticationError("bad key")

    monkeypatch.setattr(embeddings, "_get_client", lambda: _FakeClient())

    result = await _real_embed_texts(["some text"])

    assert result is None
    assert calls["n"] == 1


async def test_embed_query_uses_query_input_type(monkeypatch: pytest.MonkeyPatch) -> None:
    """Voyage's retrieval models are asymmetric — the query side must be embedded with
    input_type="query" (not "document", used for indexed content) for good match quality.
    embed_query() delegates to embed_texts() by module-level name, which the autouse
    _fake_embeddings fixture replaces wholesale for every test — restore the real
    embed_texts here so this test actually exercises the input_type plumbing."""
    seen_input_types: list[str] = []

    class _FakeClient:
        async def embed(self, texts: list[str], *, model: str, input_type: str) -> object:
            seen_input_types.append(input_type)
            return types.SimpleNamespace(embeddings=[[0.1] * 512 for _ in texts])

    monkeypatch.setattr(embeddings, "embed_texts", _real_embed_texts)
    monkeypatch.setattr(embeddings, "_get_client", lambda: _FakeClient())

    result = await embeddings.embed_query("does acme sponsor visas")

    assert seen_input_types == ["query"]
    assert result is not None
    assert len(result) == 512


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


async def test_education_create_stores_an_embedding(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    response = await client.post(
        "/profile/education",
        headers=auth_headers,
        json={"institution": "State University", "degree": "BSc", "field": "Computer Science"},
    )
    education_id = uuid.UUID(response.json()["id"])

    async with session_factory() as db:
        result = await db.execute(
            select(ProfileEmbedding).where(
                ProfileEmbedding.owner_type == "education",
                ProfileEmbedding.owner_id == education_id,
            )
        )
        embedding = result.scalar_one()
        assert "State University" in embedding.chunk_text
        assert "Computer Science" in embedding.chunk_text


async def test_education_delete_removes_embedding(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    response = await client.post(
        "/profile/education", headers=auth_headers, json={"institution": "Tech Institute"}
    )
    education_id = uuid.UUID(response.json()["id"])

    await client.delete(f"/profile/education/{education_id}", headers=auth_headers)

    async with session_factory() as db:
        result = await db.execute(
            select(ProfileEmbedding).where(
                ProfileEmbedding.owner_type == "education",
                ProfileEmbedding.owner_id == education_id,
            )
        )
        assert result.first() is None


async def test_preferences_update_stores_an_embedding(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    response = await client.put(
        "/profile/preferences",
        headers=auth_headers,
        json={"job_types": ["full_time"], "remote_preference": "remote", "locations": ["Remote"]},
    )
    assert response.status_code == 200

    # PreferencesRead has no id field (it's a per-user singleton) — resolve the row directly.
    async with session_factory() as db:
        user = (
            await db.execute(select(User).where(User.email == "profile-owner@example.com"))
        ).scalar_one()
        preferences = (
            await db.execute(select(Preferences).where(Preferences.user_id == user.id))
        ).scalar_one()

        result = await db.execute(
            select(ProfileEmbedding).where(
                ProfileEmbedding.owner_type == "preferences",
                ProfileEmbedding.owner_id == preferences.id,
            )
        )
        embedding = result.scalar_one()
        assert "full_time" in embedding.chunk_text
        assert "remote" in embedding.chunk_text
