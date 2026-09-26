"""Red-team Track A, item 4: JWT and token-handling attacks. Confirms what already holds
(tamper/expiry rejection, token-type confusion) and documents one real, deliberately unfixed
gap — refresh-token reuse (see app.auth.router.refresh's docstring) — as a design-decision item
rather than silently patching it (it would need real statefulness this scheme doesn't have
today). The other gap this track originally found here, no login rate limiting, has since been
fixed — see tests/test_rate_limit.py for that coverage."""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
from httpx import AsyncClient

from app.auth.security import create_token
from app.config import get_settings

REGISTER_PAYLOAD = {"email": "aziz@example.com", "password": "correct-horse-battery"}


async def _register_and_login(client: AsyncClient) -> dict[str, str]:
    await client.post("/auth/register", json=REGISTER_PAYLOAD)
    login = await client.post(
        "/auth/login",
        data={"username": REGISTER_PAYLOAD["email"], "password": REGISTER_PAYLOAD["password"]},
    )
    return login.json()


async def test_a_token_signed_with_the_wrong_secret_is_rejected(client: AsyncClient) -> None:
    tokens = await _register_and_login(client)
    payload = jwt.decode(tokens["access_token"], options={"verify_signature": False})
    forged = jwt.encode(payload, "not-the-real-secret", algorithm="HS256")

    response = await client.get("/auth/me", headers={"Authorization": f"Bearer {forged}"})

    assert response.status_code == 401


async def test_a_token_with_a_flipped_signature_byte_is_rejected(client: AsyncClient) -> None:
    tokens = await _register_and_login(client)
    header, payload, signature = tokens["access_token"].split(".")
    tampered_char = "A" if signature[-1] != "A" else "B"
    tampered = f"{header}.{payload}.{signature[:-1]}{tampered_char}"

    response = await client.get("/auth/me", headers={"Authorization": f"Bearer {tampered}"})

    assert response.status_code == 401


async def test_an_expired_access_token_is_rejected(client: AsyncClient) -> None:
    await client.post("/auth/register", json=REGISTER_PAYLOAD)
    settings = get_settings()
    expired_payload = {
        "sub": "00000000-0000-0000-0000-000000000000",
        "type": "access",
        "iat": datetime.now(UTC) - timedelta(hours=2),
        "exp": datetime.now(UTC) - timedelta(hours=1),
    }
    expired = jwt.encode(expired_payload, settings.app_secret_key, algorithm=settings.jwt_algorithm)

    response = await client.get("/auth/me", headers={"Authorization": f"Bearer {expired}"})

    assert response.status_code == 401


async def test_a_refresh_token_cannot_be_used_as_an_access_token(client: AsyncClient) -> None:
    tokens = await _register_and_login(client)

    response = await client.get(
        "/auth/me", headers={"Authorization": f"Bearer {tokens['refresh_token']}"}
    )

    assert response.status_code == 401


async def test_an_access_token_cannot_be_used_to_refresh(client: AsyncClient) -> None:
    tokens = await _register_and_login(client)

    response = await client.post("/auth/refresh", json={"refresh_token": tokens["access_token"]})

    assert response.status_code == 401


async def test_an_oauth_state_token_cannot_be_used_as_an_access_token(client: AsyncClient) -> None:
    # A state token is minted for OAuth handshakes (app.gmail.oauth etc.), never for API auth.
    state_token = create_token(uuid.uuid4(), "oauth_state")

    response = await client.get("/auth/me", headers={"Authorization": f"Bearer {state_token}"})

    assert response.status_code == 401


async def test_FINDING_a_refresh_token_is_reusable_after_being_used(client: AsyncClient) -> None:
    """Documented gap, deliberately left as-is (user decision, 2026-09-23 — see the docstring
    on app.auth.router.refresh for the full reasoning): using a refresh token to mint a new pair
    does not invalidate the refresh token that was just used. The same token can be replayed
    until its own 14-day expiry, which is the textbook definition of *not* having refresh-token
    rotation. Accepted for now under this app's single-user/local-only threat model; MUST be
    revisited before any public or production deployment."""
    tokens = await _register_and_login(client)
    refresh_token = tokens["refresh_token"]

    first_use = await client.post("/auth/refresh", json={"refresh_token": refresh_token})
    second_use = await client.post("/auth/refresh", json={"refresh_token": refresh_token})

    assert first_use.status_code == 200
    # Today's actual behavior: the same refresh token still works a second time. If this ever
    # starts failing, refresh-token rotation has been added — update this test, don't just
    # relax it.
    assert second_use.status_code == 200
