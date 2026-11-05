from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.models.invoice import InvoiceOut, invoice_doc_to_out
from app.repositories.invoice import InvoiceRepository
from app.services.invoices import is_overdue


class InvoiceService:
    def __init__(self, db: AsyncIOMotorDatabase[Any]) -> None:
        self._repo = InvoiceRepository(db)

    async def list_invoices(
        self,
        *,
        customer_id: str | None = None,
        status_filter: str | None = None,
        overdue_only: bool = False,
    ) -> list[InvoiceOut]:
        if customer_id:
            docs = await self._repo.list_by_customer(customer_id)
        else:
            docs = await self._repo.list_all()

        results: list[InvoiceOut] = []
        for doc in docs:
            if status_filter and doc.get("status") != status_filter:
                continue
            overdue = is_overdue(doc)
            if overdue_only and not overdue:
                continue
            results.append(invoice_doc_to_out(doc, is_overdue=overdue))
        return results

    async def get_invoice(self, invoice_number: str) -> InvoiceOut:
        doc = await self._repo.get_by_number(invoice_number)
        if doc is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Invoice {invoice_number} not found",
            )
        return invoice_doc_to_out(doc, is_overdue=is_overdue(doc))
