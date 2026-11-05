"""Bonus: payment-email evidence boosts matches but never alone."""

from __future__ import annotations

from app.services.matching import match_credit
from app.services.matching.config import EMAIL_EVIDENCE_BOOST, REVIEW_MIN
from app.services.payment_email_evidence import extract_payment_claims
from tests.helpers_matching import load_customers, load_open_invoices


def test_extract_paid_invoice_and_utr() -> None:
    claims = extract_payment_claims(
        "We paid INV-1004 yesterday via UTR-HDFC998877."
    )
    assert "INV-1004" in claims["invoice_numbers"]
    assert "HDFC998877" in claims["references"]


def test_email_evidence_alone_cannot_match() -> None:
    """Amount-only + email claim must still be none (no payer)."""
    invoices = load_open_invoices()
    customers = load_customers()
    inv = next(i for i in invoices if i.invoice_number == "INV-1004")
    evidence = [
        {
            "evidence_id": "pev_test",
            "invoice_numbers": ["INV-1004"],
            "references": [],
            "excerpt": "paid INV-1004",
        }
    ]
    result = match_credit(
        narration="NEFT CR UNKNOWN PAYER",
        payment_minor=inv.outstanding_minor,
        currency=inv.currency,
        txn_date="2026-10-01",
        invoices=invoices,
        customers=customers,
        email_evidence=evidence,
    )
    assert result.suggestion_type.value == "none"


def test_email_evidence_boosts_existing_candidate() -> None:
    invoices = load_open_invoices()
    customers = load_customers()
    inv = next(i for i in invoices if i.invoice_number == "INV-1004")
    without = match_credit(
        narration="NEFT CR KESTREL FOODS PRIVATE LIMITED INV 1004",
        payment_minor=inv.outstanding_minor,
        currency=inv.currency,
        txn_date="2026-10-01",
        invoices=invoices,
        customers=customers,
    )
    with_ev = match_credit(
        narration="NEFT CR KESTREL FOODS PRIVATE LIMITED INV 1004",
        payment_minor=inv.outstanding_minor,
        currency=inv.currency,
        txn_date="2026-10-01",
        invoices=invoices,
        customers=customers,
        email_evidence=[
            {
                "evidence_id": "pev_test",
                "invoice_numbers": ["INV-1004"],
                "references": [],
                "excerpt": "We paid INV-1004",
            }
        ],
    )
    assert without.suggestion_type.value == "single"
    assert with_ev.suggestion_type.value == "single"
    assert with_ev.confidence >= without.confidence
    assert with_ev.confidence - without.confidence <= EMAIL_EVIDENCE_BOOST + 0.1
    assert with_ev.evidence.get("email_evidence")
    # Boost cannot invent a match from below review alone — still below would stay none;
    # here the base already clears REVIEW_MIN.
    assert with_ev.confidence >= REVIEW_MIN
