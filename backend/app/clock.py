"""Single clock for 'today'. Overridable via DEMO_TODAY (YYYY-MM-DD)."""

from __future__ import annotations

from datetime import date, datetime, timezone

from app.config import get_settings


def today() -> date:
    """Return the application 'today' date (local calendar, or DEMO_TODAY)."""
    settings = get_settings()
    if settings.demo_today:
        return date.fromisoformat(settings.demo_today.strip())
    return datetime.now().astimezone().date()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
