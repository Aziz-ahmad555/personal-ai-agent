import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

RiskLevel = Literal["green", "yellow", "red"]
ActionStatus = Literal["pending_approval", "approved", "rejected", "completed", "failed"]


class AuditLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    action: str
    risk_level: RiskLevel
    status: ActionStatus
    summary: str
    evidence: dict[str, Any] | None
    resource_type: str | None
    resource_id: uuid.UUID | None
    second_check_passed: bool | None
    result: dict[str, Any] | None
    error: str | None
    requested_at: datetime
    decided_at: datetime | None
    decided_by: uuid.UUID | None


class ApprovalDecision(BaseModel):
    approved: bool
    second_check_passed: bool = Field(
        default=False,
        description="Must be true for a red-risk action's approval to be honored.",
    )
