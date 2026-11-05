"""Overdue reminder sending (one email per customer)."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.clock import today, utc_now
from app.config import Settings, get_settings
from app.integrations.protocols import OutboundEmail, SmtpClient
from app.repositories.collections import CollectionsRepository
from app.repositories.customer import CustomerRepository
from app.repositories.invoice import InvoiceRepository
from app.repositories.organization import OrganizationRepository
from app.services.email_templates import reminder_body
from app.services.invoices import is_overdue


class ReminderService:
    def __init__(
        self,
        db: AsyncIOMotorDatabase[Any],
        smtp: SmtpClient,
        settings: Settings | None = None,
    ) -> None:
        self.db = db
        self.smtp = smtp
        self.settings = settings or get_settings()
        self.repo = CollectionsRepository(db)
        self.invoices = InvoiceRepository(db)
        self.customers = CustomerRepository(db)
        self.org = OrganizationRepository(db)

    async def send_reminders(self) -> dict[str, Any]:
        lock_owner = uuid.uuid4().hex
        if not await self.repo.acquire_lock("reminders", lock_owner):
            return {
                "ok": False,
                "error": "Another reminder run is in progress",
                "sent": [],
                "skipped": [],
            }
        try:
            return await self._send_reminders_unlocked()
        finally:
            await self.repo.release_lock("reminders", lock_owner)

    async def _send_reminders_unlocked(self) -> dict[str, Any]:
        org = await self.org.get()
        if org is None:
            return {"ok": False, "error": "Organization not seeded", "sent": [], "skipped": []}

        invoices = await self.invoices.list_all()
        customers = {c["customer_id"]: c for c in await self.customers.list_all()}
        on = today()
        overdue_by_customer: dict[str, list[dict[str, Any]]] = {}
        for inv in invoices:
            if is_overdue(inv, on=on):
                overdue_by_customer.setdefault(inv["customer_id"], []).append(inv)

        sent: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        cooldown = timedelta(hours=self.settings.reminder_cooldown_hours)

        for customer_id, invs in sorted(overdue_by_customer.items()):
            customer = customers.get(customer_id)
            if customer is None:
                skipped.append({"customer_id": customer_id, "reason": "customer_missing"})
                continue

            conv = await self.repo.find_by_customer(customer_id)
            now = utc_now()
            if conv and conv.get("last_reminder_at"):
                last = datetime_from_iso(conv["last_reminder_at"])
                if last and now - last < cooldown:
                    skipped.append(
                        {
                            "customer_id": customer_id,
                            "reason": "cooldown",
                            "last_reminder_at": conv["last_reminder_at"],
                        }
                    )
                    continue

            conversation_id = (
                conv["conversation_id"] if conv else f"AC-{uuid.uuid4().hex[:10]}"
            )
            token = (
                conversation_id
                if conversation_id.startswith("AC-")
                else f"AC-{conversation_id}"
            )
            subject = (
                f"Payment reminder [{token}] — "
                f"{len(invs)} overdue invoice(s)"
            )
            body = reminder_body(
                contact_name=customer["contact_name"],
                invoices=invs,
                org=org,
            )
            message_id = f"<{uuid.uuid4().hex}@acmecorp.local>"
            await self.smtp.send(
                OutboundEmail(
                    to_address=customer["contact_email"],
                    subject=subject,
                    body=body,
                    message_id=message_id,
                    conversation_id=conversation_id,
                )
            )
            await self.repo.upsert_conversation(
                {
                    "conversation_id": conversation_id,
                    "customer_id": customer_id,
                    "kind": "customer",
                    "status": "open",
                    "subject": subject,
                    "last_reminder_at": now.isoformat(),
                    "updated_at": now.isoformat(),
                    "created_at": conv.get("created_at") if conv else now.isoformat(),
                }
            )
            await self.repo.insert_message(
                {
                    "message_id": message_id,
                    "conversation_id": conversation_id,
                    "direction": "outbound",
                    "kind": "reminder",
                    "subject": subject,
                    "body": body,
                    "from_address": self.settings.smtp_user or "accounts@acmecorp.local",
                    "to_address": customer["contact_email"],
                    "created_at": now.isoformat(),
                }
            )
            await self.db.audit_log.insert_one(
                {
                    "action": "reminder_sent",
                    "customer_id": customer_id,
                    "conversation_id": conversation_id,
                    "invoice_numbers": [i["invoice_number"] for i in invs],
                    "created_at": now.isoformat(),
                }
            )
            sent.append(
                {
                    "customer_id": customer_id,
                    "conversation_id": conversation_id,
                    "invoice_numbers": [i["invoice_number"] for i in invs],
                }
            )

        return {"ok": True, "sent": sent, "skipped": skipped}


def datetime_from_iso(value: str):
    from datetime import datetime

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
