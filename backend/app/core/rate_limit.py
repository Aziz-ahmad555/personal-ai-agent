"""Inbound rate limiting. Backed by the same Redis instance as everything else (`settings.
redis_url`) via slowapi/limits, so it survives process restarts and works correctly even if
multiple backend workers are ever run. Tests override REDIS_URL to `memory://` (see
tests/conftest.py) so the suite exercises the real limiting logic without a live Redis
connection — `limits` treats a `memory://` storage URI identically to a real backend from the
Limiter's point of view.

Login/registration were the only endpoints limited for a while: they're the one place an
unauthenticated caller can make the server do repeated work (password hashing, DB lookups) tied
to a guessable identity (an email address) — a credential-stuffing / brute-force shape. That
reasoning ("every other endpoint needs a bearer token first, which bounds abuse to one trusted
user's own audit trail") holds for the real personal deployment, where only its one owner ever
has a token — and stops holding the moment a shared *demo* account exists, since then many
anonymous visitors share that one token. LLM_ACTION_RATE_LIMIT exists for that case: every
endpoint that triggers a real LLM call (research queries; career match/verify/tailor/cover-
letter/practice generation; job-posting capture and feed polling) is limited per-IP, so the
existing global daily-spend cap (app.research.llm.SpendGuardedProvider) can't be exhausted by
one visitor alone in the first few minutes. Generous enough for one real person exploring the
demo; not generous enough for a script.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import get_settings

limiter = Limiter(
    key_func=get_remote_address, storage_uri=get_settings().effective_rate_limit_storage_uri
)

LLM_ACTION_RATE_LIMIT = "10/hour"
