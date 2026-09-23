"""Inbound rate limiting. Backed by the same Redis instance as everything else (`settings.
redis_url`) via slowapi/limits, so it survives process restarts and works correctly even if
multiple backend workers are ever run. Tests override REDIS_URL to `memory://` (see
tests/conftest.py) so the suite exercises the real limiting logic without a live Redis
connection — `limits` treats a `memory://` storage URI identically to a real backend from the
Limiter's point of view.

Login/registration are the only endpoints limited today: they're the one place an unauthenticated
caller can make the server do repeated work (password hashing, DB lookups) tied to a guessable
identity (an email address), which is exactly the shape of a credential-stuffing / brute-force
attack. Every other endpoint requires a valid bearer token first, which already bounds abuse to
an authenticated user's own audit trail.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import get_settings

limiter = Limiter(
    key_func=get_remote_address, storage_uri=get_settings().effective_rate_limit_storage_uri
)
