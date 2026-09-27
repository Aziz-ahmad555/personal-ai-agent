"""The public demo's real security controls: two complementary dependencies gating opposite
directions.

`require_not_demo_mode` refuses a request outright when `settings.demo_mode` is on, for every
route the public demo must never actually execute — real OAuth start/callback, full-account
deletion, and job-posting capture by URL (see Settings.demo_mode's own docstring for why that
one specifically). Enforced server-side on the route itself, not just hidden in the frontend —
a direct API call gets the same refusal a disabled button implies.

`require_demo_mode` is the mirror image, for app.auth.router's `/demo-login` — a route that
must be unreachable on the real, personal deployment. It 404s rather than 403s when demo mode
is off, so the route looks like it doesn't exist at all, the same convention this app already
uses for routes with no authorized backing (see the README's LinkedIn/Indeed/Fiverr handling).
"""

from typing import Annotated

from fastapi import Depends, HTTPException, status

from app.config import Settings, get_settings

DEMO_MODE_MESSAGE = "Not available in demo mode."

# scripts/seed_demo.py creates exactly this user; app.auth.router's /demo-login looks it up by
# this same constant rather than either module guessing independently.
DEMO_USER_EMAIL = "demo@personal-ai-agent.example"


def require_not_demo_mode(
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    if settings.demo_mode:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=DEMO_MODE_MESSAGE)


def require_demo_mode(
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    if not settings.demo_mode:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
