"""Generate match candidates: singletons and multi-invoice sets."""

from __future__ import annotations

from collections.abc import Sequence
from itertools import combinations

from app.money import tds_expected_payment_minor
from app.services.matching import config as cfg
from app.services.matching.types import AmountMatchKind, OpenInvoice


def open_invoices_only(invoices: Sequence[OpenInvoice]) -> list[OpenInvoice]:
    """status=sent AND outstanding > 0. Draft/paid never candidates."""
    return [
        inv
        for inv in invoices
        if inv.status == "sent" and inv.outstanding_minor > 0
    ]


def classify_amount(
    payment_minor: int, invoice: OpenInvoice
) -> AmountMatchKind:
    if payment_minor == invoice.outstanding_minor:
        return AmountMatchKind.EXACT_OUTSTANDING
    if payment_minor == invoice.total_minor:
        return AmountMatchKind.EXACT_TOTAL
    tds_pay = tds_expected_payment_minor(
        total_minor=invoice.total_minor,
        subtotal_minor=invoice.subtotal_minor,
        currency=invoice.currency,
    )
    if tds_pay is not None and payment_minor == tds_pay:
        return AmountMatchKind.TDS_ADJUSTED
    if 0 < payment_minor < invoice.outstanding_minor:
        return AmountMatchKind.PARTIAL
    if payment_minor > invoice.outstanding_minor:
        return AmountMatchKind.OVERPAY
    return AmountMatchKind.MISMATCH


def multi_invoice_sets(
    invoices: Sequence[OpenInvoice],
    payment_minor: int,
    *,
    currency: str,
) -> list[tuple[tuple[OpenInvoice, ...], AmountMatchKind]]:
    """
    Subset-sum over open invoices of the same customer & currency.

    Returns combinations whose outstanding sum equals payment exactly,
    or equals sum of TDS-adjusted expected payments (INR only).
    """
    by_customer: dict[str, list[OpenInvoice]] = {}
    for inv in invoices:
        if inv.currency != currency:
            continue
        by_customer.setdefault(inv.customer_id, []).append(inv)

    results: list[tuple[tuple[OpenInvoice, ...], AmountMatchKind]] = []
    combos_tried = 0

    for _customer_id, group in by_customer.items():
        n = len(group)
        max_size = min(cfg.MULTI_MAX_SIZE, n)
        for size in range(cfg.MULTI_MIN_SIZE, max_size + 1):
            for combo in combinations(group, size):
                combos_tried += 1
                if combos_tried > cfg.MULTI_MAX_COMBINATIONS:
                    return results
                outstanding_sum = sum(i.outstanding_minor for i in combo)
                if outstanding_sum == payment_minor:
                    results.append((combo, AmountMatchKind.MULTI_EXACT))
                    continue
                if currency == "INR":
                    tds_sum = 0
                    ok = True
                    for inv in combo:
                        expected = tds_expected_payment_minor(
                            total_minor=inv.total_minor,
                            subtotal_minor=inv.subtotal_minor,
                            currency=inv.currency,
                        )
                        if expected is None:
                            ok = False
                            break
                        # For unpaid invoices, TDS settlement is typically against total
                        tds_sum += expected
                    if ok and tds_sum == payment_minor:
                        results.append((combo, AmountMatchKind.MULTI_TDS))
    return results


def invoices_by_number(
    invoices: Sequence[OpenInvoice],
) -> dict[str, OpenInvoice]:
    return {inv.invoice_number.upper(): inv for inv in invoices}
