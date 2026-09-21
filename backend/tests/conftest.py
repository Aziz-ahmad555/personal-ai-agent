import os
from collections.abc import AsyncGenerator

os.environ.setdefault("APP_SECRET_KEY", "test-secret-key-not-for-production-use")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("TOKEN_ENCRYPTION_KEY", "Emb1Qfnswo7SlMmYcYu1OjTpVMmleBlkM_lpO-nh2Eo=")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client-id.apps.googleusercontent.com")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("GITHUB_CLIENT_ID", "test-github-client-id")
os.environ.setdefault("GITHUB_CLIENT_SECRET", "test-github-client-secret")

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.db import base as db_base  # noqa: E402
from app.db.base import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402

test_engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSessionFactory = async_sessionmaker(test_engine, expire_on_commit=False)


async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
    async with TestSessionFactory() as session:
        yield session


app.dependency_overrides[get_db] = _override_get_db

# BackgroundTasks (e.g. the Research Engine's pipeline) run outside FastAPI's DI scope, so
# they can't go through the get_db override above — they look up db_base.async_session_factory
# directly instead. Point that at the same in-memory test database so background work in
# tests reads/writes the tables _setup_db actually created, not the production engine.
db_base.async_session_factory = TestSessionFactory


@pytest.fixture(autouse=True)
async def _setup_db() -> AsyncGenerator[None, None]:
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.fixture(autouse=True)
def _fake_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests never call the real Voyage API. By default embeddings "succeed" with a
    deterministic fake vector, so the storage path is exercised; test_embeddings.py
    overrides this to simulate the no-API-key skip path explicitly."""

    async def _fake_embed_texts(
        texts: list[str], *, input_type: str = "document"
    ) -> list[list[float]] | None:
        return [[0.0] * 512 for _ in texts]

    monkeypatch.setattr("app.profile.embeddings.embed_texts", _fake_embed_texts)


@pytest.fixture
def session_factory() -> async_sessionmaker[AsyncSession]:
    return TestSessionFactory


@pytest.fixture
async def auth_headers(client: AsyncClient) -> dict[str, str]:
    email = "profile-owner@example.com"
    password = "correct-horse-battery"
    await client.post("/auth/register", json={"email": email, "password": password})
    login = await client.post("/auth/login", data={"username": email, "password": password})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}
