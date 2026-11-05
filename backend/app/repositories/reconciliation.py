from __future__ import annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ReturnDocument


class ReconciliationRepository:
    def __init__(self, db: AsyncIOMotorDatabase[Any]) -> None:
        self._db = db
        self.statements = db.bank_statements
        self.transactions = db.bank_transactions
        self.suggestions = db.match_suggestions
        self.payments = db.payments
        self.audit = db.audit_log
        self.invoices = db.invoices

    async def insert_statement(self, doc: dict[str, Any]) -> None:
        await self.statements.insert_one(doc)

    async def insert_transactions(self, docs: list[dict[str, Any]]) -> None:
        if docs:
            await self.transactions.insert_many(docs)

    async def insert_suggestions(self, docs: list[dict[str, Any]]) -> None:
        if docs:
            await self.suggestions.insert_many(docs)

    async def list_statements(self) -> list[dict[str, Any]]:
        cursor = self.statements.find({}, {"_id": 0}).sort("uploaded_at", -1)
        return [d async for d in cursor]

    async def get_statement(self, statement_id: str) -> dict[str, Any] | None:
        return await self.statements.find_one(
            {"statement_id": statement_id}, {"_id": 0}
        )

    async def list_transactions(self, statement_id: str) -> list[dict[str, Any]]:
        cursor = self.transactions.find(
            {"statement_id": statement_id}, {"_id": 0}
        ).sort("row_number", 1)
        return [d async for d in cursor]

    async def list_suggestions(self, statement_id: str) -> list[dict[str, Any]]:
        cursor = self.suggestions.find(
            {"statement_id": statement_id}, {"_id": 0}
        ).sort("row_number", 1)
        return [d async for d in cursor]

    async def get_suggestion(self, suggestion_id: str) -> dict[str, Any] | None:
        return await self.suggestions.find_one(
            {"suggestion_id": suggestion_id}, {"_id": 0}
        )

    async def claim_suggestion_for_approve(
        self, suggestion_id: str
    ) -> dict[str, Any] | None:
        """Atomically move pending → approving. Returns None if not pending."""
        return await self.suggestions.find_one_and_update(
            {"suggestion_id": suggestion_id, "status": "pending"},
            {"$set": {"status": "approving"}},
            projection={"_id": 0},
            return_document=ReturnDocument.AFTER,
        )

    async def mark_suggestion(
        self, suggestion_id: str, status: str, **extra: Any
    ) -> None:
        await self.suggestions.update_one(
            {"suggestion_id": suggestion_id},
            {"$set": {"status": status, **extra}},
        )

    async def find_applied_payment_for_txn(
        self, transaction_id: str
    ) -> dict[str, Any] | None:
        return await self.payments.find_one(
            {"bank_transaction_id": transaction_id, "status": "applied"},
            {"_id": 0},
        )

    async def find_applied_by_fingerprint(
        self, fingerprint: str
    ) -> dict[str, Any] | None:
        """Any previously applied row with this fingerprint (any statement)."""
        return await self.transactions.find_one(
            {"fingerprint": fingerprint, "status": "applied"},
            {"_id": 0},
        )

    async def insert_payment(self, doc: dict[str, Any]) -> None:
        await self.payments.insert_one(doc)

    async def insert_audit(self, doc: dict[str, Any]) -> None:
        await self.audit.insert_one(doc)

    async def get_invoice(self, invoice_number: str) -> dict[str, Any] | None:
        return await self.invoices.find_one(
            {"invoice_number": invoice_number}, {"_id": 0}
        )

    async def apply_invoice_payment(
        self,
        *,
        invoice_number: str,
        expected_balance: int,
        expected_paid: int,
        new_paid: int,
        new_balance: int,
        new_status: str,
        tds_written_off_delta: int,
    ) -> dict[str, Any] | None:
        """Conditional update — fails if balances changed (optimistic lock)."""
        return await self.invoices.find_one_and_update(
            {
                "invoice_number": invoice_number,
                "balance_due_minor": expected_balance,
                "amount_paid_minor": expected_paid,
            },
            {
                "$set": {
                    "amount_paid_minor": new_paid,
                    "balance_due_minor": new_balance,
                    "status": new_status,
                },
                "$inc": {"tds_written_off_minor": tds_written_off_delta},
            },
            projection={"_id": 0},
            return_document=ReturnDocument.AFTER,
        )

    async def restore_invoice(
        self,
        *,
        invoice_number: str,
        amount_paid_minor: int,
        balance_due_minor: int,
        status: str,
        tds_written_off_minor: int,
    ) -> None:
        await self.invoices.update_one(
            {"invoice_number": invoice_number},
            {
                "$set": {
                    "amount_paid_minor": amount_paid_minor,
                    "balance_due_minor": balance_due_minor,
                    "status": status,
                    "tds_written_off_minor": tds_written_off_minor,
                }
            },
        )

    async def list_open_invoices(self) -> list[dict[str, Any]]:
        cursor = self.invoices.find(
            {"status": "sent", "balance_due_minor": {"$gt": 0}},
            {"_id": 0},
        ).sort("invoice_number", 1)
        return [d async for d in cursor]

    async def update_suggestion_choice(
        self,
        suggestion_id: str,
        invoice_numbers: list[str],
        *,
        warning: str | None,
        mismatch: bool,
    ) -> dict[str, Any] | None:
        return await self.suggestions.find_one_and_update(
            {"suggestion_id": suggestion_id, "status": {"$in": ["pending", "chosen"]}},
            {
                "$set": {
                    "status": "pending",
                    "suggestion_type": "multi"
                    if len(invoice_numbers) > 1
                    else "single",
                    "invoice_numbers": invoice_numbers,
                    "manual_choice": True,
                    "mismatch_warning": warning,
                    "customer_mismatch": mismatch,
                    "reason": warning
                    or f"Manually chosen: {', '.join(invoice_numbers)}",
                    "confidence": 100.0 if not mismatch else 50.0,
                    "band": "high" if not mismatch else "review",
                }
            },
            projection={"_id": 0},
            return_document=ReturnDocument.AFTER,
        )

    async def reject_suggestion(self, suggestion_id: str) -> dict[str, Any] | None:
        return await self.suggestions.find_one_and_update(
            {"suggestion_id": suggestion_id, "status": "pending"},
            {"$set": {"status": "rejected"}},
            projection={"_id": 0},
            return_document=ReturnDocument.AFTER,
        )
