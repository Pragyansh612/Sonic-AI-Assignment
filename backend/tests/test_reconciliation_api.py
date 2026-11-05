from __future__ import annotations

from pathlib import Path

import pytest
from httpx import AsyncClient

from tests.helpers_matching import ROOT


@pytest.mark.asyncio
async def test_upload_and_approve_exact(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    sample = ROOT / "data" / "bank_statement_sample.csv"
    files = {"file": ("bank_statement_sample.csv", sample.read_bytes(), "text/csv")}
    up = await client.post(
        "/api/v1/reconciliation/upload",
        headers=admin_headers,
        files=files,
    )
    assert up.status_code == 200, up.text
    statement_id = up.json()["statement_id"]

    detail = await client.get(
        f"/api/v1/reconciliation/statements/{statement_id}",
        headers=admin_headers,
    )
    assert detail.status_code == 200
    body = detail.json()
    assert body["error_count"] == 0

    # Find INV-1004 suggestion
    sug = next(
        s
        for s in body["suggestions"]
        if s.get("invoice_numbers") == ["INV-1004"] and s["status"] == "pending"
    )

    ok = await client.post(
        f"/api/v1/reconciliation/suggestions/{sug['suggestion_id']}/approve",
        headers=admin_headers,
        json={},
    )
    assert ok.status_code == 200, ok.text

    inv = await client.get("/api/v1/invoices/INV-1004", headers=admin_headers)
    assert inv.json()["status"] == "paid"
    assert inv.json()["balance_due"]["minor"] == 0

    # Idempotent second approve → 409
    again = await client.post(
        f"/api/v1/reconciliation/suggestions/{sug['suggestion_id']}/approve",
        headers=admin_headers,
        json={},
    )
    assert again.status_code == 409


@pytest.mark.asyncio
async def test_tds_close_and_leave_open(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    # Minimal CSV: Quillon TDS payment
    csv = (
        "txn_date,narration,reference,credit,debit,currency\n"
        "2026-09-21,RTGS CR-QUILLON TECH PVT LTD,R1,324000,,INR\n"
    )
    up = await client.post(
        "/api/v1/reconciliation/upload",
        headers=admin_headers,
        files={"file": ("tds.csv", csv.encode(), "text/csv")},
    )
    assert up.status_code == 200
    statement_id = up.json()["statement_id"]
    detail = await client.get(
        f"/api/v1/reconciliation/statements/{statement_id}",
        headers=admin_headers,
    )
    sug = next(
        s
        for s in detail.json()["suggestions"]
        if "INV-1007" in s.get("invoice_numbers", [])
    )

    # Missing tds_mode → 422
    missing = await client.post(
        f"/api/v1/reconciliation/suggestions/{sug['suggestion_id']}/approve",
        headers=admin_headers,
        json={},
    )
    assert missing.status_code == 422

    # Reset suggestion to pending after failed claim? approve rolls back to pending
    closed = await client.post(
        f"/api/v1/reconciliation/suggestions/{sug['suggestion_id']}/approve",
        headers=admin_headers,
        json={"tds_mode": "close_tds"},
    )
    assert closed.status_code == 200, closed.text
    inv = await client.get("/api/v1/invoices/INV-1007", headers=admin_headers)
    assert inv.json()["status"] == "paid"
    assert inv.json()["tds_written_off"]["minor"] > 0


@pytest.mark.asyncio
async def test_leave_open_partial(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    csv = (
        "txn_date,narration,reference,credit,debit,currency\n"
        "2026-09-10,UPI/ORBIS PKG/PART PAYMENT,R2,200000,,INR\n"
    )
    up = await client.post(
        "/api/v1/reconciliation/upload",
        headers=admin_headers,
        files={"file": ("partial.csv", csv.encode(), "text/csv")},
    )
    statement_id = up.json()["statement_id"]
    detail = await client.get(
        f"/api/v1/reconciliation/statements/{statement_id}",
        headers=admin_headers,
    )
    sug = next(
        s
        for s in detail.json()["suggestions"]
        if "INV-1013" in s.get("invoice_numbers", [])
    )
    resp = await client.post(
        f"/api/v1/reconciliation/suggestions/{sug['suggestion_id']}/approve",
        headers=admin_headers,
        json={"tds_mode": "leave_open"},
    )
    assert resp.status_code == 200, resp.text
    inv = await client.get("/api/v1/invoices/INV-1013", headers=admin_headers)
    body = inv.json()
    assert body["status"] == "sent"
    assert body["balance_due"]["minor"] == 47200000 - 20000000


@pytest.mark.asyncio
async def test_wrong_currency_refused_on_approve(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    csv = (
        "txn_date,narration,reference,credit,debit,currency\n"
        "2026-09-28,SWIFT CR HARBOUR ANALYTICS INV-1021,R3,12500,,EUR\n"
    )
    up = await client.post(
        "/api/v1/reconciliation/upload",
        headers=admin_headers,
        files={"file": ("fx.csv", csv.encode(), "text/csv")},
    )
    statement_id = up.json()["statement_id"]
    detail = await client.get(
        f"/api/v1/reconciliation/statements/{statement_id}",
        headers=admin_headers,
    )
    # Matcher should suggest none; force choose USD invoice then approve must fail
    sug = detail.json()["suggestions"][0]
    choose = await client.post(
        f"/api/v1/reconciliation/suggestions/{sug['suggestion_id']}/choose",
        headers=admin_headers,
        json={"invoice_numbers": ["INV-1021"]},
    )
    assert choose.status_code == 400  # currency mismatch at choose


@pytest.mark.asyncio
async def test_multi_invoice_approve(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    csv = (
        "txn_date,narration,reference,credit,debit,currency\n"
        "2026-10-12,NEFT CR-SAFFRON PEAK HOSP-OCT DUES,R4,194700,,INR\n"
    )
    up = await client.post(
        "/api/v1/reconciliation/upload",
        headers=admin_headers,
        files={"file": ("multi.csv", csv.encode(), "text/csv")},
    )
    statement_id = up.json()["statement_id"]
    detail = await client.get(
        f"/api/v1/reconciliation/statements/{statement_id}",
        headers=admin_headers,
    )
    sug = next(
        s for s in detail.json()["suggestions"] if s.get("suggestion_type") == "multi"
    )
    assert set(sug["invoice_numbers"]) == {"INV-1010", "INV-1011", "INV-1012"}
    resp = await client.post(
        f"/api/v1/reconciliation/suggestions/{sug['suggestion_id']}/approve",
        headers=admin_headers,
        json={},
    )
    assert resp.status_code == 200, resp.text
    for num in ("INV-1010", "INV-1011", "INV-1012"):
        inv = await client.get(f"/api/v1/invoices/{num}", headers=admin_headers)
        assert inv.json()["status"] == "paid"


@pytest.mark.asyncio
async def test_open_invoices_endpoint(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    r = await client.get("/api/v1/invoices/open", headers=admin_headers)
    assert r.status_code == 200
    nums = {i["invoice_number"] for i in r.json()}
    assert "INV-1006" not in nums
    assert "INV-1001" not in nums
