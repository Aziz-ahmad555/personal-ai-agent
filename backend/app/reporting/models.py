import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WeeklyDigest(Base):
    """A frozen snapshot of a rolling window (`period_start`..`period_end`) across Profile,
    Research, Career, Gmail, Calendar, and GitHub — plain aggregation, no LLM, see
    app.reporting.service. Many are allowed per user (regenerating doesn't replace an old
    one) so a past digest stays inspectable even once its window is long gone, the same
    "many, ordered by recency" precedent as app.career.models.PracticeSession.

    `data` holds the full structured digest (see ReportData in service.py) as JSON, and a PDF
    export renders *this* stored snapshot, never a live re-query — so an old digest's export
    always matches what it said when generated, even after the underlying rows change."""

    __tablename__ = "weekly_digests"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
