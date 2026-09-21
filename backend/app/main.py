import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.audit.router import router as audit_router
from app.auth.router import router as auth_router
from app.career.application_router import router as applications_router
from app.career.ats_router import router as ats_router
from app.career.cover_router import router as cover_router
from app.career.resume_router import router as resume_router
from app.career.router import router as career_router
from app.config import get_settings
from app.core.health import router as health_router
from app.gmail.router import router as gmail_router
from app.github.router import router as github_router
from app.integrations.router import router as integrations_router
from app.logging import configure_logging, get_logger
from app.profile.router import router as profile_router
from app.research.router import router as research_router
from app.search.router import router as search_router

configure_logging()
logger = get_logger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Personal AI Agent API", version="0.1.0")

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
    app.include_router(integrations_router)
    app.include_router(career_router)
    app.include_router(applications_router)
    app.include_router(resume_router)
    app.include_router(cover_router)
    app.include_router(ats_router)
    app.include_router(audit_router)

    return app


app = create_app()
