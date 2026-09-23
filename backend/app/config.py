from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root, regardless of cwd: backend/app/config.py -> backend/ -> root/
_REPO_ROOT_ENV_FILE = Path(__file__).resolve().parent.parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_REPO_ROOT_ENV_FILE, extra="ignore")

    app_env: str = "development"
    app_secret_key: str = Field(min_length=16)

    database_url: str
    redis_url: str = "redis://localhost:6379/0"

    # Storage backend for the login rate limiter (app.core.rate_limit), via the `limits`
    # library. Defaults to reusing redis_url in production. Kept as a separate field (not just
    # reusing redis_url everywhere) so tests can point it at `memory://` — a `limits`-specific
    # pseudo-scheme slowapi understands but redis-py's real client (app.core.health) does not —
    # without touching redis_url, which the health check still resolves through the real client.
    rate_limit_storage_uri: str | None = None

    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 14

    cors_origins: str = "http://localhost:5173"

    voyage_api_key: str | None = None
    voyage_model: str = "voyage-3-lite"
    voyage_embedding_dimensions: int = 512

    tavily_api_key: str | None = None

    # Which LLM backs claim extraction/report drafting — swappable without touching
    # pipeline logic (see app.research.llm.LLMProvider). "gemini" | "anthropic" | "groq".
    # Default is groq: Gemini's free-tier quota (a hard 20 requests/day at the time this was
    # last changed) proved too tight for real use, on top of a same-day 5-req/minute wall and
    # sustained server overload — Groq's free tier is far more generous. Easy to switch back
    # via this one setting if Groq shows its own problems in practice.
    llm_provider: str = "groq"

    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-haiku-4-5-20251001"

    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.6-flash"

    groq_api_key: str | None = None
    groq_model: str = "openai/gpt-oss-120b"

    research_max_sources_per_query: int = 8
    research_fetch_timeout_seconds: float = 15.0
    research_fetch_concurrency: int = 4
    research_max_content_chars: int = 20_000

    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_redirect_uri: str = "http://localhost:8000/gmail/oauth/callback"
    # Where the browser lands after the OAuth callback finishes (frontend route, not API).
    gmail_frontend_return_url: str = "http://localhost:5173/gmail"

    # Symmetric key (Fernet) for encrypting Gmail OAuth tokens at rest — these are live
    # credentials to a real inbox, more sensitive than anything else this app stores, so
    # they get defense-in-depth beyond "just another DB column". Generate with:
    # python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    token_encryption_key: str | None = None

    # GitHub App (user authorization flow). Read-only by construction: the app is registered
    # with no permissions beyond the mandatory metadata:read, and the callback refuses any
    # app that has write permissions. See README "GitHub integration".
    github_client_id: str | None = None
    github_client_secret: str | None = None
    github_redirect_uri: str = "http://localhost:8000/github/oauth/callback"
    github_frontend_return_url: str = "http://localhost:5173/github"

    # Google Calendar (read-only). Same Google Cloud project/client as Gmail
    # (google_client_id/secret above) — just its own redirect and scope, so it's a
    # separate, independently revocable grant. See app/calendar/oauth.py.
    google_calendar_redirect_uri: str = "http://localhost:8000/calendar/oauth/callback"
    calendar_frontend_return_url: str = "http://localhost:5173/calendar"

    gmail_sync_window_days: int = 180
    gmail_fetch_concurrency: int = 4
    gmail_fetch_timeout_seconds: float = 15.0

    # USAJobs' official public API (data.usajobs.gov) requires a free registered key and
    # the requester's own contact email as User-Agent — see app.career.boards. Greenhouse/
    # Lever/Ashby need no key at all (public, unauthenticated job-board APIs).
    usajobs_api_key: str | None = None
    usajobs_user_agent_email: str | None = None

    # Phase 11, Group A: three already-Green, read-only-or-pure-aggregation actions promoted
    # from "human clicks a button" to "runs on a schedule" (app.core.scheduler). Each interval
    # is independently tunable; the master flag reverts to fully-manual behavior instantly with
    # no data-model change. Deliberately excludes Gmail/Calendar (their OAuth tokens have real
    # reauth fragility — a separate, later decision) and anything that could write outside the
    # user's own local data (no such action exists yet regardless).
    background_scheduler_enabled: bool = True
    github_sync_interval_hours: int = 24
    job_feed_poll_interval_hours: int = 6
    digest_generation_interval_days: int = 7

    @property
    def effective_rate_limit_storage_uri(self) -> str:
        return self.rate_limit_storage_uri or self.redis_url

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()
