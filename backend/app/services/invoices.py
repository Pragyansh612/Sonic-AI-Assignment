"""Invoice domain rules (overdue, unpaid balance)."""

from __future__ import annotations

from datetime import date
from typing import Any

from app.clock import today as app_today


def is_overdue(doc: dict[str, Any], *, on: date | None = None) -> bool:
    """
    Overdue = status sent AND unpaid balance > 0 AND due_date < today.
    Draft invoices are never overdue.
    """
    if doc.get("status") != "sent":
        return False
    if int(doc.get("balance_due_minor", 0)) <= 0:
        return False
    due = date.fromisoformat(doc["due_date"])
    return due < (on or app_today())


def unpaid_balance_minor(doc: dict[str, Any]) -> int:
    """Current unpaid amount (balance_due after payments / TDS write-off)."""
    return int(doc.get("balance_due_minor", 0))
