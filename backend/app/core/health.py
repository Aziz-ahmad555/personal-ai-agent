from typing import Annotated, Literal

import redis.asyncio as redis
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.base import get_db

router = APIRouter(tags=["health"])

Status = Literal["ok", "error"]


class DependencyStatus(BaseModel):
    status: Status
    detail: str | None = None


class HealthResponse(BaseModel):
    status: Status
    database: DependencyStatus
    redis: DependencyStatus


@router.get("/health", response_model=HealthResponse)
async def health(db: Annotated[AsyncSession, Depends(get_db)]) -> HealthResponse:
    """Every dependency is checked live — this endpoint never reports 'ok' on a guess."""
    database_status = await _check_database(db)
    redis_status = await _check_redis()

    both_ok = database_status.status == "ok" and redis_status.status == "ok"
    overall: Status = "ok" if both_ok else "error"
    return HealthResponse(status=overall, database=database_status, redis=redis_status)


async def _check_database(db: AsyncSession) -> DependencyStatus:
    try:
        await db.execute(text("SELECT 1"))
        return DependencyStatus(status="ok")
    except Exception as exc:  # noqa: BLE001 — health check must never crash the endpoint
        return DependencyStatus(status="error", detail=str(exc))


async def _check_redis() -> DependencyStatus:
    settings = get_settings()
    client = redis.from_url(settings.redis_url)  # type: ignore[no-untyped-call]
    try:
        await client.ping()
        return DependencyStatus(status="ok")
    except Exception as exc:  # noqa: BLE001
        return DependencyStatus(status="error", detail=str(exc))
    finally:
        await client.aclose()
