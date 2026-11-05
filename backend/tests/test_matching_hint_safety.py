"""Relaxed digit-run normalisation must not invent false invoice hints."""

from __future__ import annotations

from app.services.matching import match_credit
from app.services.matching.config import AMBIGUOUS_CONFIDENCE_CAP, HIGH_CONFIDENCE
from app.services.matching.normalize import normalize_narration
from app.services.matching.types import InvoiceHintStrength
from tests.helpers_matching import load_customers, load_open_invoices


def test_date_like_fragments_do_not_create_false_hints() -> None:
    invoices = load_open_invoices()
    known = [i.invoice_number for i in invoices]
    # Nordlys has open INV-1024 and INV-1025 (equal EUR amounts) — dangerous siblings.
    narrations = [
        "SEPA CR NORDLYS RETAIL GMBH 10-25",
        "SEPA CR NORDLYS RETAIL 25-10-2026",
        "SEPA CR NORDLYS RETAIL PAYMENT 10 25 AM",
        "SEPA CR NORDLYS RETAIL UTR102412599887",
        "SEPA CR NORDLYS RETAIL REF102499887766",
    ]
    for narration in narrations:
        norm = normalize_narration(narration, known_invoice_numbers=known)
        # Must not invent INV-1024/1025 from dates / UTR digit soup alone
        hinted = {h.invoice_number for h in norm.invoice_hints}
        assert "INV-1024" not in hinted and "INV-1025" not in hinted, (
            f"{narration!r} produced hints {hinted}"
        )


def test_merged_digit_hints_are_weak_and_open_suffix_only() -> None:
    invoices = load_open_invoices()
    known = [i.invoice_number for i in invoices]

    ok = normalize_narration(
        "SEPA CR NORDLYS RETAIL RE 10-25", known_invoice_numbers=known
    )
    assert len(ok.invoice_hints) == 1
    assert ok.invoice_hints[0].invoice_number == "INV-1025"
    assert ok.invoice_hints[0].strength == InvoiceHintStrength.WEAK

    inv_merged = normalize_narration(
        "NEFT CR NORDLYS INV 10-25", known_invoice_numbers=known
    )
    assert len(inv_merged.invoice_hints) == 1
    assert inv_merged.invoice_hints[0].invoice_number == "INV-1025"
    assert inv_merged.invoice_hints[0].strength == InvoiceHintStrength.WEAK

    # Contiguous INV stays strong
    strong = normalize_narration(
        "NEFT CR NORDLYS INV-1025", known_invoice_numbers=known
    )
    assert strong.invoice_hints[0].strength == InvoiceHintStrength.STRONG

    # Full date after INV must not become a hint
    dated = normalize_narration(
        "NEFT CR NORDLYS INV 25-10-2026", known_invoice_numbers=known
    )
    assert dated.invoice_hints == ()

    # Merged digits that do not map to an open suffix → no hint
    unknown = normalize_narration(
        "NEFT CR NORDLYS RE 99-99", known_invoice_numbers=known
    )
    assert unknown.invoice_hints == ()


def test_date_utr_near_payer_never_confident_wrong_sibling() -> None:
    invoices = load_open_invoices()
    customers = load_customers()
    nord = [i for i in invoices if i.customer_id == "C008" and i.outstanding_minor > 0]
    assert len(nord) >= 2
    amount = nord[0].outstanding_minor
    currency = nord[0].currency

    cases = [
        "SEPA CR NORDLYS RETAIL GMBH 10-25",
        "SEPA CR NORDLYS RETAIL 25-10-2026",
        "SEPA CR NORDLYS RETAIL 10 25 AM SETTLEMENT",
        "SEPA CR NORDLYS RETAIL UTR102412599887",
    ]
    for narration in cases:
        result = match_credit(
            narration=narration,
            payment_minor=amount,
            currency=currency,
            txn_date="2026-10-20",
            invoices=invoices,
            customers=customers,
        )
        if result.suggestion_type.value == "none":
            continue
        # May be ambiguous review-band suggestion, but never high-confidence
        # single sibling without naming the other.
        assert result.band != "high"
        assert result.confidence < HIGH_CONFIDENCE
        alt_nums = {
            n
            for a in result.alternatives
            for n in (a.get("invoice_numbers") or [])
        }
        # If a sibling was suggested, the peer must appear in reason or alternatives
        if result.invoice_numbers:
            assert "ambiguous" in result.reason.lower() or len(alt_nums) >= 2


def test_exact_tie_siblings_review_band_lists_both() -> None:
    """Same customer, same amount, no invoice hint → capped review suggestion."""
    invoices = load_open_invoices()
    customers = load_customers()
    # Nordlys INV-1024 / INV-1025 both EUR 9200 outstanding
    result = match_credit(
        narration="SEPA CR NORDLYS RETAIL GMBH",
        payment_minor=920_000,
        currency="EUR",
        txn_date="2026-10-20",
        invoices=invoices,
        customers=customers,
    )
    assert result.suggestion_type.value == "single"
    assert result.invoice_numbers == ["INV-1024"]  # earliest due
    assert result.confidence <= AMBIGUOUS_CONFIDENCE_CAP
    assert result.confidence < HIGH_CONFIDENCE
    assert result.band == "review"
    assert "INV-1024" in result.reason and "INV-1025" in result.reason
    alt_nums = {
        n
        for a in result.alternatives
        for n in (a.get("invoice_numbers") or [])
    }
    assert "INV-1024" in alt_nums and "INV-1025" in alt_nums
