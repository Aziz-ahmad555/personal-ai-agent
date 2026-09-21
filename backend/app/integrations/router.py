"""One place that says what the agent is and isn't connected to. The unavailable platforms are
listed on purpose: they are visibly not integrated, with the reason, instead of silently missing
(or worked around)."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.db.base import get_db
from app.db.models import User
from app.github.models import GithubConnection
from app.gmail.models import GmailConnection

router = APIRouter(prefix="/integrations", tags=["integrations"])

IntegrationStatus = Literal[
    "connected", "needs_reauth", "disconnected", "not_connected", "unavailable"
]


class IntegrationRead(BaseModel):
    key: str
    label: str
    status: IntegrationStatus
    summary: str
    # Frontend route for the integration's page; None when there's nothing to open.
    path: str | None
    # Why it's unavailable; only set for status == "unavailable".
    reason: str | None = None


_UNAVAILABLE_REASON = (
    "No authorized API access for a personal developer account. Scraping or browser "
    "automation isn't an authorized channel, so nothing is built for it."
)

UNAVAILABLE = (
    ("linkedin", "LinkedIn", "Profile and job data."),
    ("indeed", "Indeed", "Job listings and applications."),
    ("fiverr", "Fiverr", "Gigs and orders."),
)


@router.get("", response_model=list[IntegrationRead])
async def list_integrations(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[IntegrationRead]:
    gmail = (
        await db.execute(select(GmailConnection).where(GmailConnection.user_id == current_user.id))
    ).scalar_one_or_none()
    github = (
        await db.execute(
            select(GithubConnection).where(GithubConnection.user_id == current_user.id)
        )
    ).scalar_one_or_none()

    entries = [
        IntegrationRead(
            key="github",
            label="GitHub",
            status=github.status if github else "not_connected",
            summary="Read-only: your public repositories, as profile evidence and a "
            "recruiter-readiness review.",
            path="/github",
        ),
        IntegrationRead(
            key="gmail",
            label="Gmail",
            status=gmail.status if gmail else "not_connected",
            summary="Read-only access to your mail.",
            path="/gmail",
        ),
    ]
    entries.extend(
        IntegrationRead(
            key=key,
            label=label,
            status="unavailable",
            summary=summary,
            path=None,
            reason=_UNAVAILABLE_REASON,
        )
        for key, label, summary in UNAVAILABLE
    )
    return entries
