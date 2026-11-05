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
        "RC",  # common reorder/typo of CR; must not become a payer token
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
        "RECVD",
        "CUST",
        "ONLINE",
        "BANK",
        "TXN",
        "SETTLEMENT",
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

# Contiguous invoice digits (INV-1025 / INV 1025 / INV1025).
_INV_CONTIGUOUS_RE = re.compile(r"\bINV[-\s]?(\d{3,6})\b", re.IGNORECASE)
_INV_COMPACT_RE = re.compile(r"\bINV(\d{3,6})\b", re.IGNORECASE)
_RE_CONTIGUOUS_RE = re.compile(r"\b(?:RE|REF)[-\s]?(\d{3,6})\b", re.IGNORECASE)

# Merged digit runs with internal spaces/hyphens (INV 10-25 → digits 1025).
# Always treated as WEAK and only when they map to an open invoice suffix.
_INV_MERGED_RE = re.compile(
    r"\bINV[-\s]?(\d+(?:[-\s]+\d+)+)\b",
    re.IGNORECASE,
)
_RE_MERGED_RE = re.compile(
    r"\b(?:RE|REF)[-\s]?(\d+(?:[-\s]+\d+)+)\b",
    re.IGNORECASE,
)
_BARE_NUM_RE = re.compile(r"\b(\d{4,6})\b")
_TIME_AMPM_RE = re.compile(
    r"\b\d{1,2}\s+\d{2}\s*(?:AM|PM)\b",
    re.IGNORECASE,
)


def _digits_only(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def _is_date_shaped(raw_number: str) -> bool:
    """
    True for full dates and bare month/day style fragments that must not become
    invoice hints (e.g. 25-10-2026, 10-25, 10/25/26).
    """
    s = (raw_number or "").strip()
    if not s:
        return False
    if _TIME_AMPM_RE.search(s):
        return True
    # 25-10-2026 / 10/25/2026 / 2026-10-25
    if re.match(r"^\d{1,4}[-\s/]\d{1,2}[-\s/]\d{1,4}$", s):
        return True
    # Two-part 10-25 / 10 25 — only date-shaped when NOT under INV/RE (caller decides).
    # Here: treat as date-shaped when both parts look like day/month (<=31) and
    # the merged length is 3-4 (so 10-25 → 1025 looks invoice-like but is date-shaped
    # for *bare* contexts). For prefixed INV/RE merged tokens the caller may still
    # accept if open-suffix maps — see _extract_hints.
    m = re.match(r"^(\d{1,2})[-\s/](\d{1,2})$", s)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if 1 <= a <= 31 and 1 <= b <= 31:
            return True
    return False


def _is_full_or_time_date(raw_number: str) -> bool:
    """Stricter: 3-part dates and AM/PM times — never valid invoice digit runs."""
    s = (raw_number or "").strip()
    if _TIME_AMPM_RE.search(s):
        return True
    return bool(re.match(r"^\d{1,4}[-\s/]\d{1,2}[-\s/]\d{1,4}$", s))


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
    cleaned = _TIME_AMPM_RE.sub(" ", cleaned)
    cleaned = _INV_CONTIGUOUS_RE.sub(" ", cleaned)
    cleaned = _INV_COMPACT_RE.sub(" ", cleaned)
    cleaned = _INV_MERGED_RE.sub(" ", cleaned)
    cleaned = _RE_CONTIGUOUS_RE.sub(" ", cleaned)
    cleaned = _RE_MERGED_RE.sub(" ", cleaned)
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

    def add_contiguous(
        raw: str, suffix_raw: str, strength: InvoiceHintStrength
    ) -> None:
        if _is_date_shaped(suffix_raw) or _is_full_or_time_date(suffix_raw):
            return
        suffix = _digits_only(suffix_raw)
        if len(suffix) < 3 or len(suffix) > 6:
            return
        canonical = suffix_map.get(suffix)
        if not canonical:
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

    def add_merged_weak(raw: str, suffix_raw: str) -> None:
        """INV/RE digit runs with internal spaces/hyphens → weak open-suffix only."""
        if _is_full_or_time_date(suffix_raw):
            return
        suffix = _digits_only(suffix_raw)
        if len(suffix) < 3 or len(suffix) > 6:
            return
        canonical = suffix_map.get(suffix)
        if not canonical:
            return
        if canonical in seen:
            return
        seen.add(canonical)
        hints.append(
            InvoiceHint(
                raw=raw,
                invoice_number=canonical,
                strength=InvoiceHintStrength.WEAK,
            )
        )

    for m in _INV_CONTIGUOUS_RE.finditer(upper):
        add_contiguous(m.group(0), m.group(1), InvoiceHintStrength.STRONG)
    for m in _INV_COMPACT_RE.finditer(upper):
        add_contiguous(m.group(0), m.group(1), InvoiceHintStrength.STRONG)
    for m in _INV_MERGED_RE.finditer(upper):
        add_merged_weak(m.group(0), m.group(1))

    for m in _RE_CONTIGUOUS_RE.finditer(upper):
        add_contiguous(m.group(0), m.group(1), InvoiceHintStrength.WEAK)
    for m in _RE_MERGED_RE.finditer(upper):
        add_merged_weak(m.group(0), m.group(1))

    for m in _BARE_NUM_RE.finditer(upper):
        start = max(0, m.start() - 4)
        window = upper[start : m.end() + 3]
        if "INV" in window or re.search(r"\b(?:RE|REF)\b", window):
            continue
        ctx_start = max(0, m.start() - 10)
        ctx = upper[ctx_start : m.end() + 10]
        if _DATE_TOKEN_RE.search(ctx) or _TIME_AMPM_RE.search(ctx):
            continue
        # Do not lift digits out of "10-25" / "25-10-2026" style fragments
        if re.search(r"\d{1,2}[-\s/]\d{1,2}([-\s/]\d{2,4})?", ctx):
            continue
        add_contiguous(m.group(0), m.group(1), InvoiceHintStrength.WEAK)

    return hints
