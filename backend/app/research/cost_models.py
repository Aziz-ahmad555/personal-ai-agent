import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class LLMSpendLedger(Base):
    """One row per real generate_structured() call that actually reached a provider — the
    durable record app.research.llm._SpendGuardedProvider checks against Settings'
    daily_spend_cap_usd before allowing the next call. A row here is deliberately created
    only *after* a call succeeds (see _SpendGuardedProvider), so the ledger is always an
    honest account of tokens actually spent, never a call that was attempted but failed."""

    __tablename__ = "llm_spend_ledger"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
