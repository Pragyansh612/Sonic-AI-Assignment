from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health(client: AsyncClient) -> None:
    r = await client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["today"] == "2026-11-05"


@pytest.mark.asyncio
async def test_organization(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    r = await client.get("/api/v1/organization", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "AcmeCorp"
    assert body["bank_details"]["account_number"] == "000111222333"
    assert "tds" in body["policies"]
    assert "10% of the invoice subtotal" in body["policies"]["tds"]


@pytest.mark.asyncio
async def test_list_customers(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    r = await client.get("/api/v1/customers", headers=admin_headers)
    assert r.status_code == 200
    customers = r.json()
    assert len(customers) == 9
    assert customers[0]["customer_id"] == "C001"


@pytest.mark.asyncio
async def test_update_customer_email_requires_token(client: AsyncClient) -> None:
    r = await client.patch(
        "/api/v1/customers/C002",
        json={"contact_email": "arjun@test.example"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_update_customer_email(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    r = await client.patch(
        "/api/v1/customers/C002",
        json={"contact_email": "arjun@test.example"},
        headers=admin_headers,
    )
    assert r.status_code == 200
    assert r.json()["contact_email"] == "arjun@test.example"

    # Invalid email rejected by pydantic
    bad = await client.patch(
        "/api/v1/customers/C002",
        json={"contact_email": "not-an-email"},
        headers=admin_headers,
    )
    assert bad.status_code == 422


@pytest.mark.asyncio
async def test_invoices_counts_and_money(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    r = await client.get("/api/v1/invoices", headers=admin_headers)
    assert r.status_code == 200
    invoices = r.json()
    assert len(invoices) == 27

    by_number = {inv["invoice_number"]: inv for inv in invoices}

    # Paid seed
    assert by_number["INV-1001"]["status"] == "paid"
    assert by_number["INV-1001"]["balance_due"]["minor"] == 0
    assert by_number["INV-1001"]["is_overdue"] is False
    assert by_number["INV-1001"]["total"]["formatted"] == "₹1,18,000.00"

    # Draft never overdue
    assert by_number["INV-1006"]["status"] == "draft"
    assert by_number["INV-1006"]["is_overdue"] is False

    # Partial payment preserved from seed (INV-1023)
    inv1023 = by_number["INV-1023"]
    assert inv1023["amount_paid"]["minor"] == 200_000
    assert inv1023["balance_due"]["minor"] == 400_000
    assert inv1023["unpaid_balance"]["minor"] == 400_000
    assert inv1023["status"] == "sent"

    # GBP half unit
    assert by_number["INV-1026"]["total"]["minor"] == 735_050
    assert by_number["INV-1026"]["total"]["formatted"] == "£7,350.50"

    # tds_written_off starts at 0
    assert by_number["INV-1007"]["tds_written_off"]["minor"] == 0


@pytest.mark.asyncio
async def test_overdue_with_demo_today(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    r = await client.get("/api/v1/invoices", params={"overdue_only": True}, headers=admin_headers)
    assert r.status_code == 200
    overdue = r.json()
    numbers = {inv["invoice_number"] for inv in overdue}

    # With DEMO_TODAY=2026-11-05: due before that, sent, balance > 0
    assert "INV-1002" in numbers  # due 2026-10-12
    assert "INV-1004" in numbers  # due 2026-09-19
    assert "INV-1003" not in numbers  # due 2027-03-02
    assert "INV-1006" not in numbers  # draft
    assert "INV-1001" not in numbers  # paid
    assert all(inv["is_overdue"] for inv in overdue)


@pytest.mark.asyncio
async def test_reset_requires_confirm_and_token(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    no_token = await client.post("/api/v1/admin/reset", json={"confirm": "RESET"})
    assert no_token.status_code == 401

    bad_confirm = await client.post(
        "/api/v1/admin/reset",
        json={"confirm": "yes"},
        headers=admin_headers,
    )
    assert bad_confirm.status_code == 400


@pytest.mark.asyncio
async def test_reset_restores_seed_email_and_partial_payment(
    client: AsyncClient,
    admin_headers: dict[str, str],
    db: Any,
) -> None:
    # Mutate email + drop a fake conversation
    await client.patch(
        "/api/v1/customers/C002",
        json={"contact_email": "changed@test.example"},
        headers=admin_headers,
    )
    await db.conversations.insert_one(
        {"conversation_id": "fake", "customer_id": "C002"}
    )
    await db.payments.insert_one({"payment_id": "p1"})

    # Also mutate invoice balance to simulate approval
    await db.invoices.update_one(
        {"invoice_number": "INV-1023"},
        {"$set": {"amount_paid_minor": 600_000, "balance_due_minor": 0, "status": "paid"}},
    )

    r = await client.post(
        "/api/v1/admin/reset",
        json={"confirm": "RESET"},
        headers=admin_headers,
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True

    cust = await client.get("/api/v1/customers/C002", headers=admin_headers)
    assert cust.json()["contact_email"] == "customer2@example.com"

    inv = await client.get("/api/v1/invoices/INV-1023", headers=admin_headers)
    body = inv.json()
    assert body["amount_paid"]["minor"] == 200_000
    assert body["balance_due"]["minor"] == 400_000
    assert body["status"] == "sent"

    assert await db.conversations.count_documents({}) == 0
    assert await db.payments.count_documents({}) == 0
