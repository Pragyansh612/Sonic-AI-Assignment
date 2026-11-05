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
    allowed_dates = set()
    for inv in context_invoices:
        allowed_dates.add(inv["due_date"])
        allowed_dates.add(inv["invoice_date"])

    # Invoice numbers in draft
    for m in _INV_RE.finditer(draft):
        num = f"INV-{m.group(1)}"
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

    # Numbers, bank identifiers, contact channels: whitelist only.
    reasons.extend(_check_numbers_and_identifiers(draft, context_invoices, org))

    # Dates
    for m in _DATE_RE.finditer(draft):
        raw = m.group(1)
        normalized = _normalize_date(raw)
        if normalized and normalized not in allowed_dates:
            # allow ignoring dates that appear only in signatures? keep strict
            reasons.append(f"Draft date {raw} not in customer invoice context")

    if _FORBIDDEN_PROMISE.search(draft):
        reasons.append("Draft promises extension/waiver/discount or marks invoice paid")

    if strict:
        return ValidationResult(ok=len(reasons) == 0, reasons=reasons)
    return ValidationResult(ok=True, reasons=reasons)  # warn-only mode still returns reasons


_CUR_MARK = {
    "₹": "INR", "RS": "INR", "RS.": "INR", "INR": "INR",
    "$": "USD", "USD": "USD", "€": "EUR", "EUR": "EUR", "£": "GBP", "GBP": "GBP",
}
_NUM_RE = re.compile(
    r"(?P<pre>₹|\bRs\.?|\bINR|\bUSD|\bEUR|\bGBP|[$€£])?\s*"
    r"(?P<num>\d[\d,]*(?:\.\d+)?)"
    r"(?:\s*(?P<post>INR\b|USD\b|EUR\b|GBP\b|rupees?\b))?",
    re.IGNORECASE,
)
_IFSC_RE = re.compile(r"\b[A-Za-z]{4}0[A-Za-z0-9]{6}\b")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)


def _org_literals(org: dict[str, Any]) -> list[str]:
    vals: list[str] = []
    for key in ("name", "address", "phone", "accounts_email"):
        vals.append(str(org.get(key) or ""))
    for v in (org.get("bank_details") or {}).values():
        vals.append(str(v or ""))
    return sorted({v for v in vals if v.strip()}, key=len, reverse=True)


def _check_numbers_and_identifiers(
    draft: str, context_invoices: list[dict[str, Any]], org: dict[str, Any]
) -> list[str]:
    reasons: list[str] = []
    text = draft
    # Whitelisted literals (org bank details / contact, this customer's PO numbers).
    literals = _org_literals(org) + [
        str(i["po_number"]) for i in context_invoices if i.get("po_number")
    ]
    for lit in literals:
        text = re.sub(re.escape(lit), " ", text, flags=re.IGNORECASE)

    for m in _EMAIL_RE.finditer(text):
        reasons.append(f"Draft contains email address {m.group(0)} not in organization details")
    text = _EMAIL_RE.sub(" ", text)
    for m in _URL_RE.finditer(text):
        reasons.append(f"Draft contains link {m.group(0)}")
    text = _URL_RE.sub(" ", text)
    for m in _IFSC_RE.finditer(text):
        reasons.append(f"Draft contains bank code {m.group(0)} not in organization details")
    text = _IFSC_RE.sub(" ", text)

    # Dates and invoice numbers are validated separately; do not read them as amounts.
    text = _DATE_RE.sub(" ", text)
    text = _INV_RE.sub(" ", text)

    allowed: set[tuple[str, int]] = set()
    for inv in context_invoices:
        for key in ("balance_due_minor", "total_minor", "amount_paid_minor"):
            allowed.add((inv["currency"], int(inv[key])))
    for cur in {i["currency"] for i in context_invoices}:
        allowed.add(
            (cur, sum(int(i["balance_due_minor"]) for i in context_invoices if i["currency"] == cur))
        )
    allowed_minor = {minor for _, minor in allowed}

    for m in _NUM_RE.finditer(text):
        digits = m.group("num").replace(",", "")
        marker = (m.group("pre") or m.group("post") or "").upper()
        currency = "INR" if marker.startswith("RUPEE") else _CUR_MARK.get(marker)
        int_part = digits.split(".")[0]
        has_amount_shape = "," in m.group("num") or "." in m.group("num") or bool(marker)
        if not has_amount_shape:
            if len(int_part) < 4:
                continue  # "Net 30", "2 days"
            if len(int_part) == 4 and 1900 <= int(int_part) <= 2100:
                continue  # stray year
        try:
            minor = major_to_minor(digits.rstrip("."))
        except Exception:  # noqa: BLE001
            reasons.append(f"Draft contains unreadable number {m.group('num')}")
            continue
        if minor == 0:
            continue
        ok = (currency, minor) in allowed if currency else minor in allowed_minor
        if not ok:
            reasons.append(
                f"Draft number {m.group('num').rstrip(',.')} does not match customer context values"
            )
    return reasons


def _normalize_date(raw: str) -> str | None:
    raw = raw.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return None
