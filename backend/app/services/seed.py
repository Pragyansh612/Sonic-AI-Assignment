"""Load ./data into MongoDB. Same logic used by CLI seed and Reset demo data."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.config import Settings, get_settings
from app.db import ensure_indexes
from app.money import major_to_minor
from app.repositories.customer import CustomerRepository
from app.repositories.invoice import InvoiceRepository
from app.repositories.organization import OrganizationRepository

RUNTIME_COLLECTIONS = (
    "conversations",
    "messages",
    "payments",
    "bank_statements",
    "bank_transactions",
    "match_suggestions",
    "audit_log",
    "email_outbox",
    "job_locks",
)


def _load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def transform_invoice(raw: dict[str, Any]) -> dict[str, Any]:
    """Convert seed JSON invoice (major units) into stored minor-unit document."""
    currency = raw["currency"]
    line_items = [
        {
            "description": item["description"],
            "quantity": item["quantity"],
            "unit_price_minor": major_to_minor(item["unit_price"]),
            "amount_minor": major_to_minor(item["amount"]),
        }
        for item in raw["line_items"]
    ]
    return {
        "invoice_number": raw["invoice_number"],
        "customer_id": raw["customer_id"],
        "customer_name": raw["customer_name"],
        "po_number": raw.get("po_number"),
        "invoice_date": raw["invoice_date"],
        "due_date": raw["due_date"],
        "payment_terms": raw["payment_terms"],
        "currency": currency,
        "line_items": line_items,
        "subtotal_minor": major_to_minor(raw["subtotal"]),
        "discount_minor": major_to_minor(raw["discount"]),
        "tax_name": raw["tax_name"],
        "tax_minor": major_to_minor(raw["tax"]),
        "total_minor": major_to_minor(raw["total"]),
        # Seed amount_paid / balance_due are the baseline (e.g. INV-1023 partial).
        "amount_paid_minor": major_to_minor(raw["amount_paid"]),
        "balance_due_minor": major_to_minor(raw["balance_due"]),
        "tds_written_off_minor": 0,
        "status": raw["status"],
    }


async def clear_runtime_collections(db: AsyncIOMotorDatabase[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for name in RUNTIME_COLLECTIONS:
        result = await db[name].delete_many({})
        counts[name] = result.deleted_count
    return counts


async def seed_from_data(
    db: AsyncIOMotorDatabase[Any],
    *,
    settings: Settings | None = None,
    clear_runtime: bool = True,
) -> dict[str, int]:
    """
    Restore organization, customers, invoices from ./data.
    Optionally clear conversations, payments, bank data, audit log.
    """
    settings = settings or get_settings()
    data_dir = settings.data_dir

    org_raw = _load_json(data_dir / "organization.json")
    customers_raw = _load_json(data_dir / "customers.json")
    invoices_raw = _load_json(data_dir / "invoices.json")

    org_repo = OrganizationRepository(db)
    customer_repo = CustomerRepository(db)
    invoice_repo = InvoiceRepository(db)

    await org_repo.replace(org_raw)
    customer_count = await customer_repo.replace_all(list(customers_raw))
    invoice_docs = [transform_invoice(inv) for inv in invoices_raw]
    invoice_count = await invoice_repo.replace_all(invoice_docs)

    runtime_counts: dict[str, int] = {}
    if clear_runtime:
        runtime_counts = await clear_runtime_collections(db)

    await ensure_indexes(db)

    return {
        "organization": 1,
        "customers": customer_count,
        "invoices": invoice_count,
        **{f"cleared_{k}": v for k, v in runtime_counts.items()},
    }


async def reset_demo_data(
    db: AsyncIOMotorDatabase[Any],
    *,
    settings: Settings | None = None,
) -> dict[str, int]:
    """Reset demo data: restore seed files and clear conversations/payments."""
    return await seed_from_data(db, settings=settings, clear_runtime=True)
