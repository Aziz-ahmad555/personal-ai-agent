"""Red-team Track A, item 4: JWT and token-handling attacks. Confirms what already holds
(tamper/expiry rejection, token-type confusion) and documents two real, unfixed gaps —
refresh-token reuse and no login rate limiting — as design-decision items rather than silently
patching them (both change real behavior: token statefulness, a new dependency)."""

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

    response = await client.post(
        "/auth/refresh", json={"refresh_token": tokens["access_token"]}
    )

    assert response.status_code == 401


async def test_an_oauth_state_token_cannot_be_used_as_an_access_token(client: AsyncClient) -> None:
    # A state token is minted for OAuth handshakes (app.gmail.oauth etc.), never for API auth.
    state_token = create_token(uuid.uuid4(), "oauth_state")

    response = await client.get("/auth/me", headers={"Authorization": f"Bearer {state_token}"})

    assert response.status_code == 401


async def test_FINDING_a_refresh_token_is_reusable_after_being_used(client: AsyncClient) -> None:
    """Documented gap, not fixed here (flagged to the user as a design-decision item — a real
    fix means tracking issued/used refresh tokens, adding statefulness to what's currently a
    fully stateless JWT scheme): using a refresh token to mint a new pair does not invalidate
    the refresh token that was just used. The same token can be replayed until its own 14-day
    expiry, which is the textbook definition of *not* having refresh-token rotation."""
    tokens = await _register_and_login(client)
    refresh_token = tokens["refresh_token"]

    first_use = await client.post("/auth/refresh", json={"refresh_token": refresh_token})
    second_use = await client.post("/auth/refresh", json={"refresh_token": refresh_token})

    assert first_use.status_code == 200
    # Today's actual behavior: the same refresh token still works a second time. If this ever
    # starts failing, refresh-token rotation has been added — update this test, don't just
    # relax it.
    assert second_use.status_code == 200


async def test_FINDING_login_has_no_rate_limit_or_lockout(client: AsyncClient) -> None:
    """Documented gap, not fixed here (flagged to the user — a real fix needs a rate-limiting
    dependency and a policy decision on thresholds/lockout duration): /auth/login accepts
    unlimited attempts against the single owner account with no throttling or lockout."""
    await client.post("/auth/register", json=REGISTER_PAYLOAD)

    statuses = []
    for _ in range(15):
        response = await client.post(
            "/auth/login",
            data={"username": REGISTER_PAYLOAD["email"], "password": "wrong-guess"},
        )
        statuses.append(response.status_code)

    # Today's actual behavior: every attempt is treated identically — no 429, no lockout.
    assert statuses == [401] * 15
