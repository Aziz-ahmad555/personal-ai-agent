import re
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import log_action
from app.auth.deps import get_current_user
from app.db.base import get_db
from app.db.models import User
from app.reporting.models import WeeklyDigest
from app.reporting.pdf import render_digest_pdf
from app.reporting.schemas import GenerateDigestRequest, WeeklyDigestRead, WeeklyDigestSummary
from app.reporting.service import create_digest

router = APIRouter(prefix="/reporting", tags=["reporting"])

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


async def _owned_digest(db: AsyncSession, digest_id: uuid.UUID, user_id: uuid.UUID) -> WeeklyDigest:
    digest = (
        await db.execute(
            select(WeeklyDigest).where(
                WeeklyDigest.id == digest_id, WeeklyDigest.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if digest is None:
        raise _NOT_FOUND
    return digest


@router.post("/digests", response_model=WeeklyDigestRead, status_code=status.HTTP_201_CREATED)
async def generate_digest(
    body: GenerateDigestRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WeeklyDigest:
    digest = await create_digest(
        db, user.id, days=body.days, lookahead_days=body.lookahead_days, trigger="manual"
    )
    await db.commit()
    return digest


@router.get("/digests", response_model=list[WeeklyDigestSummary])
async def list_digests(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[WeeklyDigest]:
    return list(
        (
            await db.execute(
                select(WeeklyDigest)
                .where(WeeklyDigest.user_id == user.id)
                .order_by(WeeklyDigest.generated_at.desc())
            )
        )
        .scalars()
        .all()
    )


@router.get("/digests/{digest_id}", response_model=WeeklyDigestRead)
async def get_digest(
    digest_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WeeklyDigest:
    return await _owned_digest(db, digest_id, user.id)


def _filename(digest: WeeklyDigest) -> str:
    slug = re.sub(r"[^0-9]+", "-", f"{digest.period_start}-{digest.period_end}").strip("-")
    return f"weekly-digest-{slug}.pdf"


@router.get("/digests/{digest_id}/export")
async def export_digest(
    digest_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    digest = await _owned_digest(db, digest_id, user.id)
    pdf_bytes = render_digest_pdf(digest)
    await log_action(
        db,
        user_id=user.id,
        action="reporting.digest.exported",
        risk_level="green",
        summary="Exported a weekly digest as PDF.",
        resource_type="weekly_digest",
        resource_id=digest.id,
    )
    await db.commit()
    filename = _filename(digest)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/digests/{digest_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_digest(
    digest_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    digest = await _owned_digest(db, digest_id, user.id)
    await log_action(
        db,
        user_id=user.id,
        action="reporting.digest.deleted",
        risk_level="green",
        summary="Deleted a weekly digest.",
        resource_type="weekly_digest",
        resource_id=digest.id,
    )
    await db.delete(digest)
    await db.commit()
