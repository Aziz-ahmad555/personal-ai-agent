import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import bcrypt
import jwt

from app.config import get_settings

TokenType = Literal[
    "access", "refresh", "oauth_state", "github_oauth_state", "calendar_oauth_state"
]


def hash_password(plain_password: str) -> str:
    return bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


def create_token(subject: uuid.UUID, token_type: TokenType) -> str:
    settings = get_settings()
    now = datetime.now(UTC)

    if token_type == "access":
        expires_delta = timedelta(minutes=settings.access_token_expire_minutes)
    elif token_type == "refresh":
        expires_delta = timedelta(days=settings.refresh_token_expire_days)
    else:
        # OAuth "state" param: only needs to survive the redirect to Google and back —
        # short-lived on purpose, since it's also this flow's CSRF protection.
        expires_delta = timedelta(minutes=10)

    payload: dict[str, Any] = {
        "sub": str(subject),
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(payload, settings.app_secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str, expected_type: TokenType) -> uuid.UUID:
    settings = get_settings()
    payload = jwt.decode(token, settings.app_secret_key, algorithms=[settings.jwt_algorithm])

    if payload.get("type") != expected_type:
        raise jwt.InvalidTokenError(f"Expected a {expected_type} token")

    return uuid.UUID(payload["sub"])
