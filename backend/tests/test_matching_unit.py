from __future__ import annotations

from app.money import major_to_minor
from app.services.matching.aliases import build_aliases
from app.services.matching.candidates import classify_amount, open_invoices_only
from app.services.matching.normalize import normalize_narration
from app.services.matching.similarity import name_similarity
from app.services.matching.types import AmountMatchKind, CustomerInfo, OpenInvoice
from tests.helpers_matching import load_customers, load_open_invoices


def test_normalize_invoice_variants() -> None:
    known = ["INV-1004", "INV-1024"]
    a = normalize_narration("IMPS/KESTREL FOODS/INV 1004", known_invoice_numbers=known)
    assert any(h.invoice_number == "INV-1004" for h in a.invoice_hints)
    assert "KESTREL" in a.payer_candidate

    b = normalize_narration("... INV1004 ...", known_invoice_numbers=known)
    assert any(h.invoice_number == "INV-1004" for h in b.invoice_hints)

    c = normalize_narration("SEPA CR NORDLYS RE 1024", known_invoice_numbers=known)
    assert any(h.invoice_number == "INV-1024" for h in c.invoice_hints)
    assert all(h.strength.value == "weak" for h in c.invoice_hints)


def test_aliases_include_abbrev_and_contact() -> None:
    cust = CustomerInfo(
        "C005", "Orbis Packaging Ltd", "Meera Iyer", "INR"
    )
    aliases = build_aliases(cust)
    assert "ORBIS PACKAGING" in aliases or any("PACKAGING" in a for a in aliases)
    assert any(a == "ORBIS PKG" or "PKG" in a for a in aliases)

    redwood = CustomerInfo(
        "C006", "Redwood Clinics Pvt Ltd", "Dr. Anil Menon", "INR"
    )
    ra = build_aliases(redwood)
    assert any("CLINIC" in a for a in ra)
    assert any("ANIL MENON" in a or a.endswith("MENON") for a in ra)
    assert "RC" not in ra


def test_aliases_drop_bank_noise_and_short_acronyms(caplog) -> None:
    from app.services.matching.aliases import (
        FORBIDDEN_ALIAS_TOKENS,
        MIN_ACRONYM_LEN,
        alias_violation_reason,
        assert_customer_aliases_safe,
    )

    # Seeded customers must satisfy the startup/seed invariant.
    assert_customer_aliases_safe(load_customers())

    for tok in ("CR", "DR", "RC", "REF", "UTR", "PAY", "BANK", "TRF", "FROM", "TO"):
        assert tok in FORBIDDEN_ALIAS_TOKENS

    noisy = CustomerInfo(
        "CX",
        "CR Pay Bank Transfer Ltd",
        "Ref Utr",
        "INR",
    )
    with caplog.at_level("WARNING"):
        aliases = build_aliases(noisy)
    # No retained alias may contain a forbidden token or be a short acronym.
    for alias in aliases:
        assert alias_violation_reason(alias) is None
        for part in alias.upper().split():
            assert part not in FORBIDDEN_ALIAS_TOKENS
            if part.isalpha() and len(alias.split()) == 1:
                assert len(part) >= MIN_ACRONYM_LEN
    assert "RC" not in aliases
    assert any("drop" in r.message.lower() or "unsafe" in r.message.lower() for r in caplog.records)


def test_similarity_abbreviation() -> None:
    score = name_similarity("ORBIS PKG", "ORBIS PACKAGING")
    assert score >= 80


def test_open_invoices_exclude_draft_and_paid() -> None:
    opens = open_invoices_only(load_open_invoices())
    numbers = {i.invoice_number for i in opens}
    assert "INV-1006" not in numbers  # draft
    assert "INV-1001" not in numbers  # paid
    # Partial: outstanding is 4000 not 6000
    inv = next(i for i in opens if i.invoice_number == "INV-1023")
    assert inv.outstanding_minor == major_to_minor(4000)


def test_classify_tds() -> None:
    inv = next(i for i in load_open_invoices() if i.invoice_number == "INV-1007")
    kind = classify_amount(major_to_minor(324000), inv)
    assert kind == AmountMatchKind.TDS_ADJUSTED


def test_draft_never_matched_even_with_hint() -> None:
    from app.services.matching import match_credit

    result = match_credit(
        narration="NEFT CR-KESTREL/INV-1006",
        payment_minor=major_to_minor(147500),
        currency="INR",
        txn_date="2026-10-15",
        invoices=load_open_invoices(),
        customers=load_customers(),
    )
    assert "INV-1006" not in result.invoice_numbers
