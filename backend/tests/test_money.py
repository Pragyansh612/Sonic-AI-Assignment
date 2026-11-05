from __future__ import annotations

from decimal import Decimal

import pytest

from app.money import (
    format_money,
    major_to_minor,
    minor_to_decimal,
    tds_amount_minor,
    tds_expected_payment_minor,
)


def test_major_to_minor_handles_half_units() -> None:
    assert major_to_minor(7350.5) == 735050
    assert major_to_minor("7350.50") == 735050
    assert major_to_minor(Decimal("0.1")) == 10


def test_indian_grouping() -> None:
    assert format_money(11_800_000, "INR") == "₹1,18,000.00"
    assert format_money(32_400_000, "INR") == "₹3,24,000.00"
    assert format_money(5_900_000, "INR") == "₹59,000.00"


def test_western_grouping() -> None:
    assert format_money(1_250_000, "USD") == "$12,500.00"
    assert format_money(920_000, "EUR") == "€9,200.00"
    assert format_money(735_050, "GBP") == "£7,350.50"


def test_minor_to_decimal_roundtrip() -> None:
    assert minor_to_decimal(735050) == Decimal("7350.50")


def test_tds_is_10_percent_of_subtotal_inr_only() -> None:
    # INV-1007: subtotal 300000 -> TDS 30000 -> expected payment 324000
    subtotal = major_to_minor(300000)
    total = major_to_minor(354000)
    assert tds_amount_minor(subtotal_minor=subtotal, currency="INR") == major_to_minor(
        30000
    )
    assert tds_expected_payment_minor(
        total_minor=total, subtotal_minor=subtotal, currency="INR"
    ) == major_to_minor(324000)

    # Non-INR: no TDS
    assert tds_amount_minor(subtotal_minor=subtotal, currency="USD") == 0
    assert (
        tds_expected_payment_minor(
            total_minor=total, subtotal_minor=subtotal, currency="USD"
        )
        is None
    )


def test_tds_uses_subtotal_not_after_discount() -> None:
    # INV-1012: subtotal 65000, discount 5000 — TDS base is still 65000
    subtotal = major_to_minor(65000)
    assert tds_amount_minor(subtotal_minor=subtotal, currency="INR") == major_to_minor(
        6500
    )


def test_format_rejects_unknown_currency() -> None:
    with pytest.raises(ValueError):
        format_money(100, "JPY")
