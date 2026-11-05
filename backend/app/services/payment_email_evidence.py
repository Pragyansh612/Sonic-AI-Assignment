"""Extract payment claims from inbound email and link them to statement rows.

Evidence may add a *capped* score boost during matching; it never creates a
match by itself (hard gates and payer/hint rules still apply).
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.clock import utc_now

INV_RE = re.compile(r"\bINV[-\s]?(\d{3,5})\b", re.IGNORECASE)
REF_RE = re.compile(
    r"\b(?:UTR|NEFT|IMPS|RTGS|REF)[-:\s/]*([A-Z0-9]{4,})\b",
    re.IGNORECASE,
)
PAID_INV_RE = re.compile(
    r"\b(?:paid|payment\s+for|settled)\b[^\n.]{0,40}\bINV[-\s]?(\d{3,5})\b",
    re.IGNORECASE,
)


def extract_payment_claims(body: str) -> dict[str, list[str]]:
    invoices = sorted(
        {
            f"INV-{m.group(1)}"
            for m in INV_RE.finditer(body or "")
        }
        | {
            f"INV-{m.group(1)}"
            for m in PAID_INV_RE.finditer(body or "")
        }
    )
    references = sorted({m.group(1).upper() for m in REF_RE.finditer(body or "")})
    return {"invoice_numbers": invoices, "references": references}


async def store_payment_email_evidence(
    db: AsyncIOMotorDatabase[Any],
    *,
    customer_id: str,
    message_id: str,
    conversation_id: str,
    body: str,
) -> dict[str, Any] | None:
    claims = extract_payment_claims(body)
    if not claims["invoice_numbers"] and not claims["references"]:
        return None
    doc = {
        "evidence_id": f"pev_{uuid.uuid4().hex[:12]}",
        "customer_id": customer_id,
        "message_id": message_id,
        "conversation_id": conversation_id,
        "invoice_numbers": claims["invoice_numbers"],
        "references": claims["references"],
        "excerpt": (body or "")[:240],
        "created_at": utc_now().isoformat(),
    }
    await db.payment_email_evidence.insert_one(doc)
    return doc


async def list_payment_email_evidence(
    db: AsyncIOMotorDatabase[Any],
) -> list[dict[str, Any]]:
    cursor = db.payment_email_evidence.find({}, {"_id": 0}).sort("created_at", -1)
    return [d async for d in cursor]


def evidence_for_transaction(
    *,
    narration: str,
    reference: str | None,
    invoice_numbers: list[str],
    evidence_docs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return evidence docs that overlap this bank row / suggestion."""
    narr_u = (narration or "").upper()
    ref_u = (reference or "").upper()
    inv_set = {n.upper() for n in invoice_numbers}
    hits: list[dict[str, Any]] = []
    for doc in evidence_docs:
        inv_hit = inv_set & {n.upper() for n in doc.get("invoice_numbers") or []}
        ref_hit = False
        for r in doc.get("references") or []:
            ru = str(r).upper()
            if ru and (ru in narr_u or (ref_u and ru in ref_u)):
                ref_hit = True
                break
        # Also match when email cites an invoice and narration contains that number
        narr_inv = False
        for n in doc.get("invoice_numbers") or []:
            digits = re.sub(r"\D", "", n)
            if digits and digits in re.sub(r"\D", "", narr_u):
                narr_inv = True
                break
        if inv_hit or ref_hit or narr_inv:
            hits.append(
                {
                    "evidence_id": doc.get("evidence_id"),
                    "message_id": doc.get("message_id"),
                    "invoice_numbers": doc.get("invoice_numbers") or [],
                    "references": doc.get("references") or [],
                    "excerpt": doc.get("excerpt") or "",
                    "matched_via": (
                        "invoice"
                        if inv_hit
                        else "reference"
                        if ref_hit
                        else "narration"
                    ),
                }
            )
    return hits
