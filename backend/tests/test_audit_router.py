import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.service import log_action, request_approval
from app.auth.security import decode_token


async def _current_user_id(auth_headers: dict[str, str]) -> uuid.UUID:
    token = auth_headers["Authorization"].removeprefix("Bearer ")
    return decode_token(token, expected_type="access")


async def test_list_logs_returns_only_the_current_users_rows(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    user_id = await _current_user_id(auth_headers)

    async with session_factory() as db:
        await log_action(
            db,
            user_id=user_id,
            action="career.job.captured_from_url",
            risk_level="green",
            summary="Captured a job posting.",
        )
        await db.commit()

    response = await client.get("/audit/logs", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["action"] == "career.job.captured_from_url"
    assert body[0]["risk_level"] == "green"
    assert body[0]["status"] == "completed"


async def test_decide_endpoint_approves_a_pending_yellow_action(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    user_id = await _current_user_id(auth_headers)

    async with session_factory() as db:
        pending = await request_approval(
            db,
            user_id=user_id,
            action="gmail.send_draft",
            risk_level="yellow",
            summary="Send a drafted reply.",
        )
        await db.commit()
        log_id = str(pending.id)

    response = await client.post(
        f"/audit/logs/{log_id}/decide", headers=auth_headers, json={"approved": True}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "approved"


async def test_decide_endpoint_refuses_a_red_action_without_second_check(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    user_id = await _current_user_id(auth_headers)

    async with session_factory() as db:
        pending = await request_approval(
            db, user_id=user_id, action="career.application.submit", risk_level="red", summary="s"
        )
        await db.commit()
        log_id = str(pending.id)

    response = await client.post(
        f"/audit/logs/{log_id}/decide", headers=auth_headers, json={"approved": True}
    )
    assert response.status_code == 409


async def test_get_log_404s_for_another_users_log(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from app.db.models import User

    async with session_factory() as db:
        other = User(email=f"other-{uuid.uuid4()}@example.com", hashed_password="x")
        db.add(other)
        await db.flush()
        log = await log_action(
            db, user_id=other.id, action="x", risk_level="green", summary="s"
        )
        await db.commit()
        log_id = str(log.id)

    response = await client.get(f"/audit/logs/{log_id}", headers=auth_headers)
    assert response.status_code == 404
