"""Stable fingerprint for bank rows across uploads."""

from __future__ import annotations

import hashlib
import re


def transaction_fingerprint(
    *,
    txn_date: str,
    narration: str,
    amount_minor: int,
    reference: str,
    currency: str,
) -> str:
    """
    sha256 of normalized date|narration|amount_minor|reference|currency.

    Narration is uppercased and whitespace-collapsed; reference trimmed.
    """
    narr = re.sub(r"\s+", " ", (narration or "").strip().upper())
    ref = (reference or "").strip()
    cur = (currency or "").strip().upper()
    raw = f"{txn_date}|{narr}|{amount_minor}|{ref}|{cur}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
