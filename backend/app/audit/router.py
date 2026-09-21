import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditLog
from app.audit.schemas import ApprovalDecision, AuditLogRead
from app.audit.service import ApprovalError, decide_approval
from app.auth.deps import get_current_user
from app.db.base import get_db
from app.db.models import User

router = APIRouter(prefix="/audit", tags=["audit"])

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


@router.get("/logs", response_model=list[AuditLogRead])
async def list_logs(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    risk_level: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[AuditLog]:
    stmt = select(AuditLog).where(AuditLog.user_id == user.id)
    if status_filter:
        stmt = stmt.where(AuditLog.status == status_filter)
    if risk_level:
        stmt = stmt.where(AuditLog.risk_level == risk_level)
    stmt = stmt.order_by(AuditLog.requested_at.desc()).limit(limit)
    return list((await db.execute(stmt)).scalars().all())


@router.get("/logs/{log_id}", response_model=AuditLogRead)
async def get_log(
    log_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AuditLog:
    result = await db.execute(
        select(AuditLog).where(AuditLog.id == log_id, AuditLog.user_id == user.id)
    )
    log = result.scalar_one_or_none()
    if log is None:
        raise _NOT_FOUND
    return log


@router.post("/logs/{log_id}/decide", response_model=AuditLogRead)
async def decide(
    log_id: uuid.UUID,
    body: ApprovalDecision,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AuditLog:
    try:
        log = await decide_approval(
            db,
            audit_log_id=log_id,
            user_id=user.id,
            approved=body.approved,
            second_check_passed=body.second_check_passed,
        )
    except ApprovalError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await db.commit()
    await db.refresh(log)
    return log
