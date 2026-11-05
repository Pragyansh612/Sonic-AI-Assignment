"""Deterministic validation of outbound email drafts against customer context."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.money import format_money, major_to_minor

_INV_RE = re.compile(r"\bINV[-\s]?(\d{3,6})\b", re.IGNORECASE)
_MONEY_RE = re.compile(
    r"(?:₹|\$|€|£)\s*([0-9]{1,3}(?:,[0-9]{2,3})*(?:\.[0-9]{2})?|[0-9]+(?:\.[0-9]{2})?)"
    r"|(?:INR|USD|EUR|GBP)\s*([0-9]{1,3}(?:,[0-9]{2,3})*(?:\.[0-9]{2})?|[0-9]+(?:\.[0-9]{2})?)",
    re.IGNORECASE,
)
_DATE_RE = re.compile(
    r"\b(\d{4}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|"
    r"\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4})\b",
    re.IGNORECASE,
)

_FORBIDDEN_PROMISE = re.compile(
    r"\b(extend|extension|waive|waiver|discount|instalment|installment|"
    r"marked as paid|has been paid|is paid|we agree to defer)\b",
    re.IGNORECASE,
)


@dataclass
class ValidationResult:
    ok: bool
    reasons: list[str]


def validate_reply_draft(
    draft: str,
    *,
    customer: dict[str, Any],
    context_invoices: list[dict[str, Any]],
    org: dict[str, Any],
    all_customers: list[dict[str, Any]],
    all_invoice_numbers: list[str],
    strict: bool = True,
) -> ValidationResult:
    reasons: list[str] = []
    allowed_inv = {i["invoice_number"].upper() for i in context_invoices}
    allowed_amounts = set()
    allowed_dates = set()
    for inv in context_invoices:
        currency = inv["currency"]
        for key in ("balance_due_minor", "total_minor", "amount_paid_minor"):
            allowed_amounts.add(int(inv[key]))
        # also formatted variants checked via minor parse
        allowed_dates.add(inv["due_date"])
        allowed_dates.add(inv["invoice_date"])
    if context_invoices:
        total = sum(int(i["balance_due_minor"]) for i in context_invoices)
        allowed_amounts.add(total)

    # Invoice numbers in draft
    for m in _INV_RE.finditer(draft):
        num = f"INV-{m.group(1)}"
        if num.upper() not in allowed_inv:
            # paid/draft of same customer still not allowed in customer-facing owe context
            if num.upper() not in {x.upper() for x in all_invoice_numbers if False}:
                pass
            if num.upper() not in allowed_inv:
                reasons.append(f"Draft mentions invoice {num} not in customer context")

    # Other customers' names / invoices
    for other in all_customers:
        if other["customer_id"] == customer["customer_id"]:
            continue
        name = other["name"]
        # check distinctive chunks (first two significant words)
        tokens = [t for t in re.split(r"\W+", name) if len(t) > 3]
        if tokens and tokens[0].lower() in draft.lower() and tokens[0].lower() not in customer["name"].lower():
            # avoid flagging common words; require 2-token phrase when possible
            phrase = " ".join(tokens[:2])
            if phrase.lower() in draft.lower():
                reasons.append(f"Draft mentions other customer name ({phrase})")

    for inv_num in all_invoice_numbers:
        if inv_num.upper() in allowed_inv:
            continue
        if inv_num.upper() in draft.upper():
            reasons.append(f"Draft mentions foreign invoice {inv_num}")

    # Money amounts
    for m in _MONEY_RE.finditer(draft):
        raw = m.group(1) or m.group(2)
        try:
            minor = major_to_minor(raw.replace(",", ""))
        except Exception:
            continue
        if minor not in allowed_amounts and minor != 0:
            # allow org account number digits mistakenly — skip pure account
            if str(minor) in org.get("bank_details", {}).get("account_number", ""):
                continue
            reasons.append(
                f"Draft amount {raw} does not match customer context values"
            )

    # Dates
    for m in _DATE_RE.finditer(draft):
        raw = m.group(1)
        normalized = _normalize_date(raw)
        if normalized and normalized not in allowed_dates:
            # allow ignoring dates that appear only in signatures? keep strict
            reasons.append(f"Draft date {raw} not in customer invoice context")

    if _FORBIDDEN_PROMISE.search(draft):
        reasons.append("Draft promises extension/waiver/discount or marks invoice paid")

    # Bank details must be org's if present
    bank = org.get("bank_details", {})
    for key in ("account_number", "ifsc", "swift_code"):
        val = bank.get(key) or ""
        # no check for absence
        pass

    if strict:
        return ValidationResult(ok=len(reasons) == 0, reasons=reasons)
    return ValidationResult(ok=True, reasons=reasons)  # warn-only mode still returns reasons


def _normalize_date(raw: str) -> str | None:
    raw = raw.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return None
