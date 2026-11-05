"""Deterministic email fact blocks rendered from DB values (not LLM)."""

from __future__ import annotations

from typing import Any

from app.money import format_money


def format_overdue_invoice_lines(invoices: list[dict[str, Any]]) -> str:
    lines = []
    for inv in invoices:
        currency = inv["currency"]
        outstanding = int(inv["balance_due_minor"])
        lines.append(
            f"- {inv['invoice_number']}: {format_money(outstanding, currency)} "
            f"due {inv['due_date']}"
        )
    return "\n".join(lines)


def total_outstanding_formatted(invoices: list[dict[str, Any]]) -> str:
    if not invoices:
        return ""
    currency = invoices[0]["currency"]
    total = sum(int(i["balance_due_minor"]) for i in invoices)
    return format_money(total, currency)


def payment_details_block(org: dict[str, Any]) -> str:
    bank = org["bank_details"]
    methods = ", ".join(org.get("payment_methods") or [])
    return (
        f"You can pay by {methods} to {bank['account_name']}, "
        f"account {bank['account_number']}, {bank['bank']}, "
        f"IFSC {bank['ifsc']}"
        + (f", SWIFT {bank['swift_code']}" if bank.get("swift_code") else "")
        + "."
    )


def reminder_body(
    *,
    contact_name: str,
    invoices: list[dict[str, Any]],
    org: dict[str, Any],
) -> str:
    lines = format_overdue_invoice_lines(invoices)
    total = total_outstanding_formatted(invoices)
    pay = payment_details_block(org)
    return (
        f"Dear {contact_name},\n\n"
        f"This is a reminder that the following invoice(s) are overdue:\n"
        f"{lines}\n\n"
        f"Total outstanding: {total}.\n\n"
        f"{pay}\n\n"
        f"Kind regards,\n{org.get('accounts_contact_name', 'Accounts Team')}\n"
        f"{org.get('name', 'AcmeCorp')}\n"
    )


def compose_customer_reply(
    *,
    contact_name: str,
    prose: str,
    invoices: list[dict[str, Any]],
    org: dict[str, Any],
    include_invoices: bool,
    include_payment_details: bool,
) -> str:
    parts = [f"Dear {contact_name},", "", prose.strip()]
    if include_invoices and invoices:
        parts.extend(
            [
                "",
                "Outstanding invoices:",
                format_overdue_invoice_lines(invoices),
                f"Total: {total_outstanding_formatted(invoices)}.",
            ]
        )
    if include_payment_details:
        parts.extend(["", payment_details_block(org)])
    parts.extend(
        [
            "",
            f"Kind regards,\n{org.get('accounts_contact_name', 'Accounts Team')}",
        ]
    )
    return "\n".join(parts)
