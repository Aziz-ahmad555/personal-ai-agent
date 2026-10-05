import os
from collections.abc import AsyncGenerator
from datetime import UTC, date, datetime

os.environ.setdefault("APP_SECRET_KEY", "test-secret-key-not-for-production-use")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("TOKEN_ENCRYPTION_KEY", "eozxtJev26O9zrNqtEAS3zTq00aNtt9IaalJtg5qBZo=")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client-id.apps.googleusercontent.com")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("GITHUB_CLIENT_ID", "test-github-client-id")
os.environ.setdefault("GITHUB_CLIENT_SECRET", "test-github-client-secret")
# The rate limiter (app.core.rate_limit) needs a `limits` storage backend at import time.
# `memory://` gives the suite the real limiting logic (not mocked) with no live Redis
# dependency — same reasoning as DATABASE_URL being sqlite in-memory above. Deliberately a
# separate env var from REDIS_URL: app.core.health's real redis-py client doesn't understand
# the `memory://` pseudo-scheme and would raise before its own try/except could catch it.
os.environ.setdefault("RATE_LIMIT_STORAGE_URI", "memory://")
# The background scheduler (app.core.scheduler) only starts via app.main's lifespan handler,
# which httpx's ASGITransport never triggers unless a test explicitly wires up lifespan
# support — so this is belt-and-suspenders, not load-bearing, but keeps a real interval
# scheduler from ever running against the test database if that ever changes.
os.environ.setdefault("BACKGROUND_SCHEDULER_ENABLED", "false")

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import event  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.core.rate_limit import limiter  # noqa: E402
from app.db import base as db_base  # noqa: E402
from app.db.base import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402

test_engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSessionFactory = async_sessionmaker(test_engine, expire_on_commit=False)


@event.listens_for(test_engine.sync_engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection: object, _: object) -> None:
    """SQLite ignores every `ondelete=CASCADE`/`ondelete=SET NULL` in the schema unless a
    connection turns this on explicitly — off by default, unlike Postgres (which the real
    app runs on and always enforces these). Without it, a test deleting a parent row would
    silently leave every child row behind, one connection pragma away from actually proving
    the cascade real Postgres already performs."""
    dbapi_connection.execute("PRAGMA foreign_keys=ON")


def utc_today() -> date:
    """The UTC calendar date — use this in any test building fixture data that a date-
    boundary check will compare against, instead of the stdlib's date.today() (the *local*
    calendar date). The two disagree for several hours a day in any timezone that isn't
    UTC (this machine included, UTC+5), and the app itself is consistently UTC-based for
    every such check (app.reporting.service's digest, app.career.application_rules'
    follow_up_state, ...) — a test built on the local date can silently test the wrong side
    of midnight. This happened for real once already: a fixture dated "yesterday" via
    date.today() landed on "today" by the app's own UTC reckoning, turning an intended
    "overdue" case into "due_today" and failing test_reporting_digest.py for a few hours
    every day, in a way that had nothing to do with whatever change was actually being
    tested. Importable directly — `from conftest import utc_today` — since date.today()
    is often called inline (request payloads, non-fixture helper functions), not just from
    a test's own body where a pytest fixture could be injected."""
    return datetime.now(UTC).date()


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
def _reset_rate_limiter() -> None:
    """The limiter's in-memory storage is a module-level singleton (app.core.rate_limit.limiter),
    so without this, register/login calls in one test would count against the limit in the
    next one — every test using the `auth_headers` fixture would eventually start failing with
    429 instead of the login/register behavior it actually means to exercise. Real Redis-backed
    production use has no equivalent problem since each real client already has its own IP."""
    limiter.reset()


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
