import uuid
from typing import Annotated

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.deps import get_current_user
from app.db import base as db_base
from app.db.base import get_db
from app.db.models import User
from app.research.llm import start_cost_guarded_task
from app.research.models import (
    ResearchClaim,
    ResearchQuery,
    ResearchQuerySource,
    ResearchSource,
)
from app.research.pipeline import run_research_query
from app.research.schemas import (
    ClaimRead,
    ResearchQueryCreate,
    ResearchQueryDetail,
    ResearchQueryRead,
    SourceRead,
)

router = APIRouter(prefix="/research", tags=["research"])

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


async def _run_in_background(query_id: uuid.UUID) -> None:
    """Background tasks run after the response is sent, once the request's own DB session
    may already be closed — so this opens a fresh session rather than reusing the request's.
    Looked up as db_base.async_session_factory (an attribute access at call time, not a
    name bound at import time) so tests can point it at their own test database the same
    way they override the get_db dependency — a plain `from ... import async_session_factory`
    would silently keep using the production engine even when get_db is overridden, since
    BackgroundTasks run outside FastAPI's dependency-injection scope."""
    structlog.contextvars.bind_contextvars(task_id=str(query_id))
    start_cost_guarded_task()  # enables SpendGuardedProvider's enforcement for this task
    async with db_base.async_session_factory() as db:
        await run_research_query(db, query_id)


@router.post("/queries", response_model=ResearchQueryRead, status_code=status.HTTP_201_CREATED)
async def create_query(
    body: ResearchQueryCreate,
    background_tasks: BackgroundTasks,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ResearchQuery:
    query = ResearchQuery(user_id=user.id, query_text=body.query_text, purpose=body.purpose)
    db.add(query)
    await db.commit()
    await db.refresh(query)

    background_tasks.add_task(_run_in_background, query.id)
    return query


@router.get("/queries", response_model=list[ResearchQueryRead])
async def list_queries(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[ResearchQuery]:
    result = await db.execute(
        select(ResearchQuery)
        .where(ResearchQuery.user_id == user.id)
        .order_by(ResearchQuery.created_at.desc())
    )
    return list(result.scalars().all())


async def _get_owned_query(
    db: AsyncSession, query_id: uuid.UUID, user_id: uuid.UUID
) -> ResearchQuery:
    result = await db.execute(
        select(ResearchQuery).where(ResearchQuery.id == query_id, ResearchQuery.user_id == user_id)
    )
    query = result.scalar_one_or_none()
    if query is None:
        raise _NOT_FOUND
    return query


@router.get("/queries/{query_id}", response_model=ResearchQueryDetail)
async def get_query(
    query_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ResearchQueryDetail:
    query = await _get_owned_query(db, query_id, user.id)

    source_rows = (
        (
            await db.execute(
                select(ResearchSource)
                .join(ResearchQuerySource, ResearchQuerySource.source_id == ResearchSource.id)
                .where(ResearchQuerySource.query_id == query_id)
                .order_by(ResearchQuerySource.search_rank)
            )
        )
        .scalars()
        .all()
    )

    claim_rows = (
        (
            await db.execute(
                select(ResearchClaim)
                .where(ResearchClaim.query_id == query_id)
                .options(selectinload(ResearchClaim.citations))
                .order_by(ResearchClaim.confidence_score.desc())
            )
        )
        .scalars()
        .all()
    )

    await db.refresh(query, attribute_names=["report"])

    return ResearchQueryDetail(
        id=query.id,
        query_text=query.query_text,
        purpose=query.purpose,
        status=query.status,
        error=query.error,
        created_at=query.created_at,
        completed_at=query.completed_at,
        sources=[SourceRead.model_validate(s) for s in source_rows],
        claims=[ClaimRead.model_validate(c) for c in claim_rows],
        report=query.report,
    )


@router.get("/sources/{source_id}", response_model=SourceRead)
async def get_source(
    source_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ResearchSource:
    # Sources aren't user-owned (they're deduplicated/shared across queries), so ownership
    # is enforced one hop out: the source must have been collected by one of this user's
    # queries, or it isn't this user's to see.
    result = await db.execute(
        select(ResearchSource)
        .join(ResearchQuerySource, ResearchQuerySource.source_id == ResearchSource.id)
        .join(ResearchQuery, ResearchQuery.id == ResearchQuerySource.query_id)
        .where(ResearchSource.id == source_id, ResearchQuery.user_id == user.id)
    )
    source = result.scalars().first()
    if source is None:
        raise _NOT_FOUND
    return source
