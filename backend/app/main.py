import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.audit.router import router as audit_router
from app.auth.router import router as auth_router
from app.calendar.router import router as calendar_router
from app.calendar.sync_router import router as calendar_sync_router
from app.career.application_router import router as applications_router
from app.career.ats_router import router as ats_router
from app.career.cover_router import router as cover_router
from app.career.practice_router import router as practice_router
from app.career.resume_router import router as resume_router
from app.career.router import router as career_router
from app.config import get_settings
from app.core.health import router as health_router
from app.core.rate_limit import limiter
from app.core.scheduler import build_scheduler
from app.github.readiness_router import router as github_readiness_router
from app.github.router import router as github_router
from app.github.sync_router import router as github_sync_router
from app.gmail.router import router as gmail_router
from app.integrations.router import router as integrations_router
from app.logging import configure_logging, get_logger
from app.profile.router import router as profile_router
from app.reporting.router import router as reporting_router
from app.research.router import router as research_router
from app.search.router import router as search_router

configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    scheduler = None
    if settings.background_scheduler_enabled:
        scheduler = build_scheduler(settings)
        scheduler.start()
        logger.info(
            "background_scheduler_started",
            github_sync_interval_hours=settings.github_sync_interval_hours,
            job_feed_poll_interval_hours=settings.job_feed_poll_interval_hours,
            digest_generation_interval_days=settings.digest_generation_interval_days,
        )
    app.state.scheduler = scheduler
    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Personal AI Agent API", version="0.1.0", lifespan=_lifespan)

    app.state.limiter = limiter
    # slowapi's handler predates Starlette's generic Request/Response typing.
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
    app.add_middleware(SlowAPIMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def log_requests(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = str(uuid.uuid4())
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        logger.info(
            "http_request",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        response.headers["X-Request-ID"] = request_id
        return response

    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(profile_router)
    app.include_router(research_router)
    app.include_router(search_router)
    app.include_router(gmail_router)
    app.include_router(github_router)
    app.include_router(github_sync_router)
    app.include_router(github_readiness_router)
    app.include_router(calendar_router)
    app.include_router(calendar_sync_router)
    app.include_router(integrations_router)
    app.include_router(career_router)
    app.include_router(applications_router)
    app.include_router(resume_router)
    app.include_router(cover_router)
    app.include_router(practice_router)
    app.include_router(ats_router)
    app.include_router(reporting_router)
    app.include_router(audit_router)

    return app


app = create_app()
