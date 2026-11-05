"""Shared pytest fixtures. Uses a dedicated Mongo database."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from motor.motor_asyncio import AsyncIOMotorDatabase

# Configure env before app imports settings (cached).
os.environ.setdefault("MONGODB_URI", "mongodb://localhost:27017")
os.environ["MONGODB_DB"] = "acmecorp_test"
os.environ["ADMIN_API_TOKEN"] = "test-admin-token"
os.environ["FRONTEND_ORIGIN"] = "http://localhost:3000"
# Deterministic overdue checks for Part A tests
os.environ["DEMO_TODAY"] = "2026-11-05"

from app.config import get_settings  # noqa: E402
from app.db import close_client, ensure_indexes, get_client, get_db  # noqa: E402
from app.main import create_app  # noqa: E402
from app.services.seed import seed_from_data  # noqa: E402

get_settings.cache_clear()


@pytest_asyncio.fixture
async def db() -> AsyncIterator[AsyncIOMotorDatabase[Any]]:
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.mongodb_db == "acmecorp_test"
    database = get_db(settings)
    # Drop entire test DB for isolation
    await get_client(settings).drop_database(settings.mongodb_db)
    await ensure_indexes(database)
    await seed_from_data(database, settings=settings, clear_runtime=True)
    yield database
    await get_client(settings).drop_database(settings.mongodb_db)
    await close_client()
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def client(db: AsyncIOMotorDatabase[Any]) -> AsyncIterator[AsyncClient]:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def admin_headers() -> dict[str, str]:
    return {"X-Admin-Token": "test-admin-token"}
