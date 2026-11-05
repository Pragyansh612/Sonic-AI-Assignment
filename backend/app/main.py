"""FastAPI application entrypoint."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app import __version__
from app.config import get_settings
from app.db import close_client, ensure_indexes, get_db
from app.routes import admin, customers, health, invoices, organization, reconciliation


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], object]
    ) -> Response:
        response = await call_next(request)  # type: ignore[misc]
        assert isinstance(response, Response)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    await ensure_indexes(get_db())
    yield
    await close_client()


def create_app() -> FastAPI:
    settings = get_settings()
    settings.assert_secure_for_environment()
    application = FastAPI(
        title="AcmeCorp Accounts API",
        version=__version__,
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Admin-Token"],
    )
    application.add_middleware(SecurityHeadersMiddleware)

    application.include_router(health.router, prefix="/api/v1")
    application.include_router(organization.router, prefix="/api/v1")
    application.include_router(customers.router, prefix="/api/v1")
    application.include_router(invoices.router, prefix="/api/v1")
    application.include_router(admin.router, prefix="/api/v1")
    application.include_router(reconciliation.router, prefix="/api/v1")
    return application


app = create_app()
