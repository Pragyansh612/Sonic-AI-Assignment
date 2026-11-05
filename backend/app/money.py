"""Money helpers: Decimal in code, integer minor units in Mongo, never floats."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Final

MINOR_FACTOR: Final[int] = 100  # all supported currencies use 2 decimal places

CURRENCY_SYMBOLS: Final[dict[str, str]] = {
    "INR": "₹",
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
}

SUPPORTED_CURRENCIES: Final[frozenset[str]] = frozenset(CURRENCY_SYMBOLS)


def to_decimal(value: object) -> Decimal:
    """Parse a numeric value into Decimal without float rounding surprises."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return Decimal(value)
    if isinstance(value, str):
        cleaned = value.strip().replace(",", "")
        if not cleaned:
            raise ValueError("empty money string")
        return Decimal(cleaned)
    # JSON floats / numpy-like: go via str to reduce binary float artifacts
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"cannot parse money value: {value!r}") from exc


def major_to_minor(major: object) -> int:
    """Convert major currency units (e.g. 118000.00) to integer minor units."""
    amount = to_decimal(major)
    minor = (amount * MINOR_FACTOR).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(minor)


def minor_to_decimal(minor: int) -> Decimal:
    return (Decimal(minor) / Decimal(MINOR_FACTOR)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def format_money(minor: int, currency: str) -> str:
    """Format minor units for display. INR uses Indian grouping."""
    currency = currency.upper()
    if currency not in SUPPORTED_CURRENCIES:
        raise ValueError(f"unsupported currency: {currency}")
    symbol = CURRENCY_SYMBOLS[currency]
    absolute = abs(minor)
    whole, frac = divmod(absolute, MINOR_FACTOR)
    sign = "-" if minor < 0 else ""
    if currency == "INR":
        grouped = _indian_group(whole)
    else:
        grouped = f"{whole:,}"
    return f"{sign}{symbol}{grouped}.{frac:02d}"


def _indian_group(whole: int) -> str:
    """Indian numbering: last 3 digits, then groups of 2 (e.g. 1,18,000)."""
    s = str(whole)
    if len(s) <= 3:
        return s
    last3 = s[-3:]
    rest = s[:-3]
    parts: list[str] = []
    while rest:
        parts.append(rest[-2:])
        rest = rest[:-2]
    return ",".join(reversed(parts)) + "," + last3


def tds_amount_minor(*, subtotal_minor: int, currency: str) -> int:
    """
    TDS is 10% of invoice subtotal (not after discount), INR customers only.

    Per organization.policies.tds / data-explanation.md.
    """
    if currency.upper() != "INR":
        return 0
    return int(
        (Decimal(subtotal_minor) * Decimal("0.10")).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )


def tds_expected_payment_minor(
    *, total_minor: int, subtotal_minor: int, currency: str
) -> int | None:
    """Amount a customer may remit when deducting TDS (INR only)."""
    if currency.upper() != "INR":
        return None
    tds = tds_amount_minor(subtotal_minor=subtotal_minor, currency=currency)
    return total_minor - tds
