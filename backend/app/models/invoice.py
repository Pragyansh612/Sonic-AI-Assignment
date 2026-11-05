from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.common import MoneyField


class InvoiceStatus(str, Enum):
    DRAFT = "draft"
    SENT = "sent"
    PAID = "paid"


class LineItemOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    description: str
    quantity: int | float
    unit_price: MoneyField
    amount: MoneyField


class InvoiceOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    invoice_number: str
    customer_id: str
    customer_name: str
    po_number: str | None
    invoice_date: str
    due_date: str
    payment_terms: str
    currency: str
    line_items: list[LineItemOut]
    subtotal: MoneyField
    discount: MoneyField
    tax_name: str
    tax: MoneyField
    total: MoneyField
    amount_paid: MoneyField
    balance_due: MoneyField
    tds_written_off: MoneyField
    status: InvoiceStatus
    is_overdue: bool = Field(
        description="sent AND unpaid balance > 0 AND due_date < today"
    )
    unpaid_balance: MoneyField = Field(
        description="Current unpaid amount (balance_due after payments/TDS)"
    )


class ResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm: str = Field(
        description='Must be exactly "RESET" to proceed',
        examples=["RESET"],
    )


class ResetResponse(BaseModel):
    ok: bool
    message: str
    counts: dict[str, int]


class HealthResponse(BaseModel):
    status: str
    today: str
    demo_today: str | None


def invoice_doc_to_out(doc: dict[str, Any], *, is_overdue: bool) -> InvoiceOut:
    currency = doc["currency"]
    balance_minor = int(doc["balance_due_minor"])
    tds_minor = int(doc.get("tds_written_off_minor", 0))

    def m(minor_key: str) -> MoneyField:
        return MoneyField.from_minor(int(doc[minor_key]), currency)

    line_items = [
        LineItemOut(
            description=item["description"],
            quantity=item["quantity"],
            unit_price=MoneyField.from_minor(int(item["unit_price_minor"]), currency),
            amount=MoneyField.from_minor(int(item["amount_minor"]), currency),
        )
        for item in doc["line_items"]
    ]

    return InvoiceOut(
        invoice_number=doc["invoice_number"],
        customer_id=doc["customer_id"],
        customer_name=doc["customer_name"],
        po_number=doc.get("po_number"),
        invoice_date=doc["invoice_date"],
        due_date=doc["due_date"],
        payment_terms=doc["payment_terms"],
        currency=currency,
        line_items=line_items,
        subtotal=m("subtotal_minor"),
        discount=m("discount_minor"),
        tax_name=doc["tax_name"],
        tax=m("tax_minor"),
        total=m("total_minor"),
        amount_paid=m("amount_paid_minor"),
        balance_due=MoneyField.from_minor(balance_minor, currency),
        tds_written_off=MoneyField.from_minor(tds_minor, currency),
        status=InvoiceStatus(doc["status"]),
        is_overdue=is_overdue,
        unpaid_balance=MoneyField.from_minor(balance_minor, currency),
    )
