"""Narration normalization and invoice-token extraction."""

from __future__ import annotations

import re
from collections.abc import Iterable

from app.services.matching.types import (
    InvoiceHint,
    InvoiceHintStrength,
    NormalizedNarration,
)

# Transfer / noise tokens stripped from payer candidate text.
_METHOD_TOKENS = frozenset(
    {
        "NEFT",
        "RTGS",
        "IMPS",
        "UPI",
        "SWIFT",
        "SEPA",
        "CR",
        "DR",
        "TRF",
        "TRANSFER",
        "PAYMENT",
        "PART",
        "PYMT",
        "PMT",
        "TO",
        "FROM",
        "VIA",
        "BY",
        "OCT",
        "NOV",
        "DEC",
        "JAN",
        "FEB",
        "MAR",
        "APR",
        "MAY",
        "JUN",
        "JUL",
        "AUG",
        "SEP",
        "DUES",
        "DUE",
        "CLINIC",  # kept? No - CLINIC can be part of payer; don't strip generically
    }
)

# Tokens that are almost always bank noise (safe to strip globally).
_NOISE_ALWAYS = frozenset(
    {
        "NEFT",
        "RTGS",
        "IMPS",
        "UPI",
        "SWIFT",
        "SEPA",
        "CR",
        "DR",
        "TRF",
        "TRANSFER",
        "PAYMENT",
        "PART",
        "PYMT",
        "PMT",
        "INTPD",
        "INT",
        "PD",
        "INTEREST",
    }
)

_UTR_RE = re.compile(
    r"\b(?:UTR|REF(?:ERENCE)?|RRN|CHQ|CHEQUE)[-:]?\s*[A-Z0-9]{6,}\b",
    re.IGNORECASE,
)
_LONG_REF_RE = re.compile(r"\b[A-Z]?\d{10,}\b")
_BANK_CODE_RE = re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")  # IFSC-like
_DATE_TOKEN_RE = re.compile(
    r"\b(?:\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|\d{4}-\d{2}-\d{2}|"
    r"\d{1,2}\s+(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\s+\d{2,4})\b",
    re.IGNORECASE,
)
# Allow optional spaces/hyphens inside the digit run (INV 10-25 → 1025).
_INV_STRONG_RE = re.compile(
    r"\bINV[-\s]?((?:\d[-\s]?){2,6}\d)\b",
    re.IGNORECASE,
)
_INV_COMPACT_RE = re.compile(r"\bINV((?:\d[-\s]?){2,6}\d)\b", re.IGNORECASE)
_RE_REF_RE = re.compile(
    r"\b(?:RE|REF)[-\s]?((?:\d[-\s]?){2,6}\d)\b",
    re.IGNORECASE,
)
_BARE_NUM_RE = re.compile(r"\b(\d{4,6})\b")


def _digits_only(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def normalize_narration(
    narration: str,
    *,
    known_invoice_numbers: Iterable[str] | None = None,
) -> NormalizedNarration:
    """
    Uppercase, strip transfer-method prefixes/noise, extract invoice hints.

    known_invoice_numbers: used so weak/bare numeric hints only fire when the
    digits map to an existing invoice suffix (e.g. 1024 → INV-1024).
    """
    original = narration or ""
    upper = original.upper()

    known = {n.upper() for n in (known_invoice_numbers or [])}
    suffix_map = _build_suffix_map(known)

    hints = _extract_hints(upper, suffix_map)

    # Remove invoice tokens and refs before building payer candidate
    cleaned = upper
    cleaned = _UTR_RE.sub(" ", cleaned)
    cleaned = _BANK_CODE_RE.sub(" ", cleaned)
    cleaned = _LONG_REF_RE.sub(" ", cleaned)
    cleaned = _DATE_TOKEN_RE.sub(" ", cleaned)
    cleaned = _INV_STRONG_RE.sub(" ", cleaned)
    cleaned = _INV_COMPACT_RE.sub(" ", cleaned)
    cleaned = _RE_REF_RE.sub(" ", cleaned)
    # INT.PD style interest markers
    cleaned = re.sub(r"\bINT\.?\s*PD\b[:\s0-9\-]*", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"[^A-Z0-9\s]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    tokens = [t for t in cleaned.split() if t and t not in _NOISE_ALWAYS]
    # Drop pure numeric leftovers (refs / dates already mostly gone)
    tokens = [t for t in tokens if not t.isdigit()]
    payer = " ".join(tokens).strip()

    return NormalizedNarration(
        original=original,
        payer_candidate=payer,
        cleaned_tokens=tuple(tokens),
        invoice_hints=tuple(hints),
    )


def _build_suffix_map(known: set[str]) -> dict[str, str]:
    """Map numeric suffix → canonical invoice number (INV-####)."""
    out: dict[str, str] = {}
    for inv in known:
        m = re.search(r"(\d+)$", inv)
        if not m:
            continue
        suffix = m.group(1)
        # Prefer INV- form
        canonical = inv if inv.startswith("INV") else f"INV-{suffix}"
        # If collision on suffix, leave ambiguous (no weak match)
        if suffix in out and out[suffix] != canonical:
            out[suffix] = ""
        else:
            out[suffix] = canonical
    return {k: v for k, v in out.items() if v}


def _extract_hints(
    upper: str, suffix_map: dict[str, str]
) -> list[InvoiceHint]:
    hints: list[InvoiceHint] = []
    seen: set[str] = set()

    def add(raw: str, suffix: str, strength: InvoiceHintStrength) -> None:
        suffix = _digits_only(suffix)
        if len(suffix) < 3 or len(suffix) > 6:
            return
        canonical = suffix_map.get(suffix)
        if not canonical:
            # Strong INV tokens: still record even if not in open set —
            # scoring will handle unknown / paid invoices.
            if strength == InvoiceHintStrength.STRONG:
                canonical = f"INV-{suffix}"
            else:
                return
        if canonical in seen:
            return
        seen.add(canonical)
        hints.append(
            InvoiceHint(raw=raw, invoice_number=canonical, strength=strength)
        )

    for m in _INV_STRONG_RE.finditer(upper):
        add(m.group(0), m.group(1), InvoiceHintStrength.STRONG)
    for m in _INV_COMPACT_RE.finditer(upper):
        add(m.group(0), m.group(1), InvoiceHintStrength.STRONG)
    for m in _RE_REF_RE.finditer(upper):
        add(m.group(0), m.group(1), InvoiceHintStrength.WEAK)
    # Bare numbers only when uniquely mapped
    for m in _BARE_NUM_RE.finditer(upper):
        # Skip if already part of a stronger match span — crude: skip if INV nearby
        start = max(0, m.start() - 4)
        window = upper[start : m.end()]
        if "INV" in window or re.search(r"\b(?:RE|REF)\b", window):
            continue
        add(m.group(0), m.group(1), InvoiceHintStrength.WEAK)

    return hints
