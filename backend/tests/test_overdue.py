from __future__ import annotations

from datetime import date

from app.services.invoices import is_overdue


def _inv(**kwargs: object) -> dict:
    base = {
        "status": "sent",
        "balance_due_minor": 100,
        "due_date": "2026-10-01",
    }
    base.update(kwargs)
    return base


def test_draft_never_overdue() -> None:
    assert not is_overdue(
        _inv(status="draft", due_date="2020-01-01"), on=date(2026, 11, 5)
    )


def test_paid_zero_balance_not_overdue() -> None:
    assert not is_overdue(
        _inv(status="paid", balance_due_minor=0), on=date(2026, 11, 5)
    )


def test_sent_unpaid_past_due_is_overdue() -> None:
    assert is_overdue(_inv(), on=date(2026, 11, 5))


def test_sent_unpaid_future_due_not_overdue() -> None:
    assert not is_overdue(
        _inv(due_date="2027-03-02"), on=date(2026, 11, 5)
    )


def test_due_today_is_not_overdue() -> None:
    assert not is_overdue(
        _inv(due_date="2026-11-05"), on=date(2026, 11, 5)
    )
