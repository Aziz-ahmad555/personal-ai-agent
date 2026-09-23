"""Login rate limiting (Phase 10 Track A follow-up — the login/registration brute-force gap
originally documented in tests/test_redteam_auth.py, now fixed via app.core.rate_limit).

/auth/login and /auth/register are the one place an unauthenticated caller can make the server
do repeated work tied to a guessable identity (an email address) — a credential-stuffing /
brute-force surface. Both are limited to 5 requests/minute per client IP via slowapi, backed by
the same Redis instance as everything else in production (`memory://` in tests — see
tests/conftest.py — which exercises the real limiting logic, not a mock).
"""

from httpx import ASGITransport, AsyncClient

from app.main import app


async def test_the_sixth_login_attempt_in_a_minute_is_rejected(client: AsyncClient) -> None:
    email = "ratelimit-login@example.com"
    await client.post("/auth/register", json={"email": email, "password": "correct-horse-battery"})

    statuses = []
    for _ in range(6):
        response = await client.post(
            "/auth/login", data={"username": email, "password": "wrong-guess"}
        )
        statuses.append(response.status_code)

    assert statuses == [401, 401, 401, 401, 401, 429]


async def test_the_fifth_login_attempt_still_succeeds_with_the_right_password(
    client: AsyncClient,
) -> None:
    email, password = "ratelimit-boundary@example.com", "correct-horse-battery"
    await client.post("/auth/register", json={"email": email, "password": password})

    for _ in range(4):
        await client.post("/auth/login", data={"username": email, "password": "wrong-guess"})

    fifth = await client.post("/auth/login", data={"username": email, "password": password})

    assert fifth.status_code == 200
    assert "access_token" in fifth.json()


async def test_the_rate_limit_response_does_not_leak_internal_details(
    client: AsyncClient,
) -> None:
    email = "ratelimit-body@example.com"
    await client.post("/auth/register", json={"email": email, "password": "correct-horse-battery"})
    for _ in range(5):
        await client.post("/auth/login", data={"username": email, "password": "wrong-guess"})

    blocked = await client.post(
        "/auth/login", data={"username": email, "password": "wrong-guess"}
    )

    assert blocked.status_code == 429
    body = str(blocked.json()).lower()
    # slowapi's default body is just {"error": "..."} — confirm it says nothing about the
    # account itself (e.g. whether it exists) beyond "you're being throttled".
    assert "password" not in body
    assert email not in body


async def test_registration_is_also_rate_limited(client: AsyncClient) -> None:
    statuses = []
    for i in range(6):
        response = await client.post(
            "/auth/register",
            json={
                "email": f"ratelimit-register-{i}@example.com",
                "password": "correct-horse-battery",
            },
        )
        statuses.append(response.status_code)

    # The first request wins the single-user bootstrap slot (201); the next four are already
    # rejected as "registration closed" (403). The 6th is rejected by the rate limiter itself
    # (429) before it even reaches that check, proving the limit applies regardless of outcome.
    assert statuses[0] == 201
    assert statuses[1:5] == [403, 403, 403, 403]
    assert statuses[5] == 429


async def test_a_different_client_ip_gets_its_own_limit(client: AsyncClient) -> None:
    """The limit key is per-IP (get_remote_address), not global — one attacker exhausting
    their own limit must not lock out the real user coming from a different address. The
    `client` fixture's ASGITransport always presents the same fake IP, so this spins up a
    second AsyncClient against the same app with a distinct fake client IP to prove isolation."""
    email, password = "ratelimit-perip@example.com", "correct-horse-battery"
    await client.post("/auth/register", json={"email": email, "password": password})

    for _ in range(5):
        response = await client.post(
            "/auth/login", data={"username": email, "password": "wrong-guess"}
        )
        assert response.status_code == 401
    exhausted = await client.post("/auth/login", data={"username": email, "password": password})
    assert exhausted.status_code == 429

    other_transport = ASGITransport(app=app, client=("10.0.0.2", 123))
    async with AsyncClient(transport=other_transport, base_url="http://test") as other_client:
        from_second_ip = await other_client.post(
            "/auth/login", data={"username": email, "password": password}
        )
    assert from_second_ip.status_code == 200
