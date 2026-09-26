"""Lifecycle for the eval harness's own Postgres database — a real database is required
(not SQLite) because the retrieval-hit-rate eval needs pgvector's cosine_distance, which has
no SQLite equivalent. Every run starts from a clean, fully-recreated schema so eval results
never depend on state left over from a previous run, and eval data never touches the real
personal_agent database.
"""

# Importing app.main (rather than individual model modules one at a time) pulls in every
# router, which transitively imports every model module — the same trick tests/conftest.py
# relies on to populate Base.metadata completely before create_all runs.
import app.main  # noqa: E402, F401
from app.config import get_settings
from app.db.base import Base
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import evals.config as eval_config  # noqa: F401 - sys.path side effect, see config.py


def _maintenance_url(eval_url: str) -> tuple[str, str]:
    """Returns (url pointing at the server's default maintenance db, target db name) so
    CREATE DATABASE has somewhere to run from — you can't create a database while connected
    to the database you're creating."""
    base, _, db_name = eval_url.rpartition("/")
    return f"{base}/postgres", db_name


async def ensure_eval_database_exists(eval_url: str) -> None:
    maintenance_url, db_name = _maintenance_url(eval_url)
    engine = create_async_engine(maintenance_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            exists = await conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": db_name}
            )
            if not exists:
                # Can't parameterize an identifier; db_name comes from our own config, not
                # user input, so this is safe.
                await conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    finally:
        await engine.dispose()


async def reset_schema(eval_url: str) -> async_sessionmaker[AsyncSession]:
    """Drops and rebuilds every table fresh, returns a session factory bound to the result.
    Call once at the start of a run (from the same asyncio.run() that will use the returned
    session factory — an async engine's connection pool is tied to the event loop it was
    created in, so this must not be wrapped in its own separate asyncio.run())."""
    await ensure_eval_database_exists(eval_url)
    engine = create_async_engine(eval_url, pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)


def eval_database_url() -> str:
    settings = get_settings()
    return eval_config.derive_eval_database_url(settings.database_url)
