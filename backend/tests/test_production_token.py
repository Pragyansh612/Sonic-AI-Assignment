from __future__ import annotations

import os

import pytest

from app.config import Settings, get_settings


def test_production_rejects_default_admin_token() -> None:
    settings = Settings(
        ENV="production",
        ADMIN_API_TOKEN="dev-admin-token",
    )
    with pytest.raises(RuntimeError, match="ADMIN_API_TOKEN"):
        settings.assert_secure_for_environment()


def test_production_rejects_short_token() -> None:
    settings = Settings(ENV="production", ADMIN_API_TOKEN="short-secret")
    with pytest.raises(RuntimeError, match="ADMIN_API_TOKEN"):
        settings.assert_secure_for_environment()


def test_production_accepts_strong_token() -> None:
    settings = Settings(
        ENV="production",
        ADMIN_API_TOKEN="a-sufficiently-long-random-token",
    )
    settings.assert_secure_for_environment()


def test_development_allows_default_token() -> None:
    settings = Settings(ENV="development", ADMIN_API_TOKEN="dev-admin-token")
    settings.assert_secure_for_environment()


def test_create_app_refuses_insecure_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("ADMIN_API_TOKEN", "dev-admin-token")
    get_settings.cache_clear()
    from app.main import create_app

    with pytest.raises(RuntimeError, match="ADMIN_API_TOKEN"):
        create_app()
    # Restore test env used by other fixtures
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("ADMIN_API_TOKEN", "test-admin-token")
    get_settings.cache_clear()
    os.environ["ADMIN_API_TOKEN"] = "test-admin-token"
    os.environ["ENV"] = "development"
