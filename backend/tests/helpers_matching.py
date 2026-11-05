from __future__ import annotations

import json
from pathlib import Path

from app.services.matching import CustomerInfo, OpenInvoice
from app.services.seed import transform_invoice

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load_open_invoices() -> list[OpenInvoice]:
    raw = json.loads((DATA / "invoices.json").read_text(encoding="utf-8"))
    out: list[OpenInvoice] = []
    for item in raw:
        d = transform_invoice(item)
        out.append(
            OpenInvoice(
                invoice_number=d["invoice_number"],
                customer_id=d["customer_id"],
                customer_name=d["customer_name"],
                currency=d["currency"],
                invoice_date=d["invoice_date"],
                due_date=d["due_date"],
                outstanding_minor=d["balance_due_minor"],
                total_minor=d["total_minor"],
                subtotal_minor=d["subtotal_minor"],
                status=d["status"],
            )
        )
    return out


def load_customers() -> list[CustomerInfo]:
    raw = json.loads((DATA / "customers.json").read_text(encoding="utf-8"))
    return [
        CustomerInfo(
            customer_id=c["customer_id"],
            name=c["name"],
            contact_name=c["contact_name"],
            currency=c["currency"],
        )
        for c in raw
    ]
