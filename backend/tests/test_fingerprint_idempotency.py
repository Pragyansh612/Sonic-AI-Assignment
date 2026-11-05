from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.services.transaction_fingerprint import transaction_fingerprint


def test_fingerprint_stable() -> None:
    a = transaction_fingerprint(
        txn_date="2026-09-10",
        narration="  upi/orbis pkg/part payment ",
        amount_minor=20_000_000,
        reference="625314770213",
        currency="inr",
    )
    b = transaction_fingerprint(
        txn_date="2026-09-10",
        narration="UPI/ORBIS PKG/PART PAYMENT",
        amount_minor=20_000_000,
        reference="625314770213",
        currency="INR",
    )
    assert a == b


@pytest.mark.asyncio
async def test_reupload_after_approve_blocks_second_application(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    csv = (
        "txn_date,narration,reference,credit,debit,currency\n"
        "2026-09-10,UPI/ORBIS PKG/PART PAYMENT,625314770213,200000,,INR\n"
    )
    up1 = await client.post(
        "/api/v1/reconciliation/upload",
        headers=admin_headers,
        files={"file": ("p1.csv", csv.encode(), "text/csv")},
    )
    assert up1.status_code == 200
    d1 = await client.get(
        f"/api/v1/reconciliation/statements/{up1.json()['statement_id']}",
        headers=admin_headers,
    )
    sug = next(
        s
        for s in d1.json()["suggestions"]
        if "INV-1013" in s.get("invoice_numbers", [])
    )
    ap = await client.post(
        f"/api/v1/reconciliation/suggestions/{sug['suggestion_id']}/approve",
        headers=admin_headers,
        json={"tds_mode": "leave_open"},
    )
    assert ap.status_code == 200, ap.text

    # Re-upload identical CSV
    up2 = await client.post(
        "/api/v1/reconciliation/upload",
        headers=admin_headers,
        files={"file": ("p2.csv", csv.encode(), "text/csv")},
    )
    assert up2.status_code == 200
    d2 = await client.get(
        f"/api/v1/reconciliation/statements/{up2.json()['statement_id']}",
        headers=admin_headers,
    )
    sug2 = d2.json()["suggestions"][0]
    assert sug2["status"] == "already_applied"
    assert sug2["suggestion_type"] == "none"

    blocked = await client.post(
        f"/api/v1/reconciliation/suggestions/{sug2['suggestion_id']}/approve",
        headers=admin_headers,
        json={"tds_mode": "leave_open"},
    )
    assert blocked.status_code == 409

    # Balance must not have been applied twice
    inv = await client.get("/api/v1/invoices/INV-1013")
    assert inv.json()["balance_due"]["minor"] == 47200000 - 20000000
