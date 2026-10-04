"""app.core.demo.require_not_demo_mode: the server-side gate behind the public demo's one real
security control. Confirms every route that must never actually execute on the public demo
(real OAuth start/callback, full-account deletion, job-posting capture by URL) refuses outright
when demo_mode is on — a direct API call must get the same refusal a disabled frontend button
implies, not just a hidden button. Overrides the get_settings dependency the same way
conftest.py already overrides get_db, rather than touching the real lru_cache'd settings
singleton other tests share."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.core.demo import DEMO_USER_EMAIL
from app.db.models import User
from app.main import app


@pytest.fixture
def demo_mode_on():
    real_settings = get_settings()
    demo_settings = real_settings.model_copy(update={"demo_mode": True})
    app.dependency_overrides[get_settings] = lambda: demo_settings
    yield
    del app.dependency_overrides[get_settings]


async def test_gmail_oauth_start_is_blocked_in_demo_mode(
    client: AsyncClient, auth_headers: dict[str, str], demo_mode_on: None
) -> None:
    response = await client.get("/gmail/oauth/start", headers=auth_headers)
    assert response.status_code == 403
    assert response.json()["detail"] == "Not available in demo mode."


async def test_gmail_oauth_callback_is_blocked_in_demo_mode(
    client: AsyncClient, demo_mode_on: None
) -> None:
    response = await client.get("/gmail/oauth/callback", params={"code": "x", "state": "y"})
    assert response.status_code == 403


async def test_calendar_oauth_start_is_blocked_in_demo_mode(
    client: AsyncClient, auth_headers: dict[str, str], demo_mode_on: None
) -> None:
    response = await client.get("/calendar/oauth/start", headers=auth_headers)
    assert response.status_code == 403


async def test_calendar_oauth_callback_is_blocked_in_demo_mode(
    client: AsyncClient, demo_mode_on: None
) -> None:
    response = await client.get("/calendar/oauth/callback", params={"code": "x", "state": "y"})
    assert response.status_code == 403


async def test_github_oauth_start_is_blocked_in_demo_mode(
    client: AsyncClient, auth_headers: dict[str, str], demo_mode_on: None
) -> None:
    response = await client.get("/github/oauth/start", headers=auth_headers)
    assert response.status_code == 403


async def test_github_oauth_callback_is_blocked_in_demo_mode(
    client: AsyncClient, demo_mode_on: None
) -> None:
    response = await client.get("/github/oauth/callback", params={"code": "x", "state": "y"})
    assert response.status_code == 403


async def test_delete_account_request_is_blocked_in_demo_mode(
    client: AsyncClient, auth_headers: dict[str, str], demo_mode_on: None
) -> None:
    response = await client.post("/auth/delete-account/request", headers=auth_headers)
    assert response.status_code == 403


async def test_delete_account_decide_is_blocked_in_demo_mode(
    client: AsyncClient, auth_headers: dict[str, str], demo_mode_on: None
) -> None:
    response = await client.post(
        "/auth/delete-account/00000000-0000-0000-0000-000000000000/decide",
        headers=auth_headers,
        json={"approved": True},
    )
    assert response.status_code == 403


async def test_job_capture_from_url_is_blocked_in_demo_mode(
    client: AsyncClient, auth_headers: dict[str, str], demo_mode_on: None
) -> None:
    response = await client.post(
        "/career/jobs/from-url",
        headers=auth_headers,
        json={"url": "https://example.com/job"},
    )
    assert response.status_code == 403


async def test_job_capture_from_paste_is_not_blocked_in_demo_mode(
    client: AsyncClient, auth_headers: dict[str, str], demo_mode_on: None
) -> None:
    """Capture by pasted text never fetches a URL, so it's outside demo mode's gate — this
    is a regression guard against someone widening the gate to cover it by mistake."""
    response = await client.post(
        "/career/jobs/paste",
        headers=auth_headers,
        json={"raw_text": "Senior Backend Engineer at Acme Corp. Remote. 5+ years Python."},
    )
    assert response.status_code != 403


async def test_gmail_sync_is_blocked_in_demo_mode(
    client: AsyncClient, auth_headers: dict[str, str], demo_mode_on: None
) -> None:
    """Seeded demo connections carry no real encrypted tokens (no real OAuth ever happened for
    them) — letting this through would mutate the seeded connection to needs_reauth and get a
    visitor stuck looking at a broken Gmail connection they can't fix (reconnect is also
    demo-blocked). No connection row exists for this test user at all; this still must 403
    before ever reaching that 404, since the demo gate runs first."""
    response = await client.post("/gmail/sync", headers=auth_headers)
    assert response.status_code == 403
    assert response.json()["detail"] == "Not available in demo mode."


async def test_github_sync_is_blocked_in_demo_mode(
    client: AsyncClient, auth_headers: dict[str, str], demo_mode_on: None
) -> None:
    response = await client.post("/github/sync", headers=auth_headers)
    assert response.status_code == 403


async def test_calendar_sync_is_blocked_in_demo_mode(
    client: AsyncClient, auth_headers: dict[str, str], demo_mode_on: None
) -> None:
    response = await client.post("/calendar/sync", headers=auth_headers)
    assert response.status_code == 403


async def test_gmail_oauth_start_works_normally_outside_demo_mode(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """No demo_mode_on fixture here — confirms the gate doesn't fire when it isn't asked to."""
    response = await client.get("/gmail/oauth/start", headers=auth_headers)
    assert response.status_code != 403


# --- /auth/demo-login ------------------------------------------------------------------------


async def test_demo_login_404s_outside_demo_mode(client: AsyncClient) -> None:
    """Looks like the route doesn't exist at all on the real deployment — see
    require_demo_mode's own docstring for why 404, not 403, here specifically."""
    response = await client.post("/auth/demo-login")
    assert response.status_code == 404


async def test_demo_login_fails_clearly_when_no_demo_user_is_seeded(
    client: AsyncClient, demo_mode_on: None
) -> None:
    response = await client.post("/auth/demo-login")
    assert response.status_code == 503


async def test_demo_login_issues_a_real_token_for_the_seeded_demo_user(
    client: AsyncClient,
    demo_mode_on: None,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as db:
        db.add(User(email=DEMO_USER_EMAIL, hashed_password="not-a-real-password-hash"))
        await db.commit()

    response = await client.post("/auth/demo-login")

    assert response.status_code == 200
    body = response.json()
    assert body["access_token"] and body["refresh_token"]

    me = await client.get("/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    assert me.json()["email"] == DEMO_USER_EMAIL
