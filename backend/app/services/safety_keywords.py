"""Deterministic keyword/regex safety net applied before trusting the LLM."""

from __future__ import annotations

import re
from typing import Any

LEGAL_RE = re.compile(
    r"\b(legal|lawyer|advocate|court|notice|sue|litigation|consumer\s+forum)\b",
    re.IGNORECASE,
)
DISPUTE_RE = re.compile(
    r"\b(dispute|incorrect|wrong\s+amount|not\s+received|overcharged)\b",
    re.IGNORECASE,
)
EXTENSION_RE = re.compile(
    r"\b(extensions?|extend\w*|more\s+time|extra\s+(?:time|days?|weeks?|months?)|"
    r"(?:more|additional|few)\s+(?:days?|weeks?|months?)|grace(?:\s+period)?|"
    r"defer\w*|postpone\w*|reschedul\w*|instal?ments?|installments?|waive\w*|"
    r"later\s+date|next\s+(?:week|month)|pay\s+(?:later|next|after)|"
    r"split\s+(?:this|the|it|payment)|push\s+(?:back|out))\b",
    re.IGNORECASE,
)


# Words that appear in company names but identify no one in particular.
_GENERIC_NAME_WORDS = frozenset(
    {
        "private", "limited", "company", "services", "solutions", "systems", "group",
        "technologies", "technology", "logistics", "foods", "retail", "media", "clinics",
        "analytics", "packaging", "hospitality", "industries", "enterprises", "global",
        "international", "holdings", "partners", "consulting", "trading", "India",
    }
)


def _distinctive_tokens(name: str) -> set[str]:
    return {
        t.lower()
        for t in re.split(r"\W+", name)
        if len(t) >= 5 and t.lower() not in {w.lower() for w in _GENERIC_NAME_WORDS}
    }


def scan_body_for_policy_hits(
    body: str,
    *,
    customer_id: str,
    all_customers: list[dict[str, Any]],
    all_invoices: list[dict[str, Any]],
) -> list[str]:
    hits: list[str] = []
    if LEGAL_RE.search(body):
        hits.append("legal")
    if DISPUTE_RE.search(body):
        hits.append("dispute")
    if EXTENSION_RE.search(body):
        hits.append("extension")

    own = next((c for c in all_customers if c["customer_id"] == customer_id), None)
    own_tokens = _distinctive_tokens(own["name"]) if own else set()
    body_lower = body.lower()
    for other in all_customers:
        if other["customer_id"] == customer_id:
            continue
        name = other["name"]
        tokens = [t for t in re.split(r"\W+", name) if len(t) > 3]
        found = False
        if len(tokens) >= 2:
            phrase = f"{tokens[0]} {tokens[1]}"
            found = phrase.lower() in body_lower
        if not found:
            for tok in _distinctive_tokens(name) - own_tokens:
                if re.search(rf"\b{re.escape(tok)}\b", body_lower):
                    found = True
                    break
        if found:
            hits.append("other_company")
            break
    for inv in all_invoices:
        if inv["customer_id"] == customer_id:
            continue
        if inv["invoice_number"].upper() in body.upper():
            hits.append("other_company")
            break
    return hits


def is_auto_reply_or_bounce(
    *,
    subject: str,
    from_address: str,
    headers: dict[str, str],
) -> tuple[bool, str | None]:
    auto_submitted = (headers.get("Auto-Submitted") or "").lower()
    if auto_submitted and auto_submitted != "no":
        return True, "auto_reply"
    precedence = (headers.get("Precedence") or "").lower()
    if precedence in {"bulk", "auto_reply", "list"}:
        return True, "auto_reply"
    if (headers.get("X-Autoreply") or "").strip():
        return True, "auto_reply"
    ctype = (headers.get("Content-Type") or "").lower()
    if "multipart/report" in ctype:
        return True, "bounce"
    sender = from_address.lower()
    if "mailer-daemon" in sender or sender.startswith("postmaster@"):
        return True, "bounce"
    subj = subject.lower()
    if "out of office" in subj or "out-of-office" in subj:
        return True, "auto_reply"
    if "undelivered" in subj or "delivery status notification" in subj:
        return True, "bounce"
    return False, None
