from __future__ import annotations

from datetime import date

from app.clock import today
from app.config import get_settings


def test_demo_today_overrides_clock() -> None:
    get_settings.cache_clear()
    assert get_settings().demo_today == "2026-11-05"
    assert today() == date(2026, 11, 5)
