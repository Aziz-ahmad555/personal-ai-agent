import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class GenerateDigestRequest(BaseModel):
    days: int = Field(default=7, ge=1, le=90)
    lookahead_days: int = Field(default=14, ge=1, le=90)


class WeeklyDigestSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    period_start: date
    period_end: date
    generated_at: datetime


class WeeklyDigestRead(WeeklyDigestSummary):
    # The full structured digest — see app.reporting.service.build_digest for the exact shape.
    # Left as a loose JSON blob rather than a fully-typed schema: it's a read-only, internally
    # consistent snapshot the frontend renders section by section, not a shape callers write to.
    data: dict[str, Any]
