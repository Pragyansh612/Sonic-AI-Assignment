from __future__ import annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase


class InvoiceRepository:
    def __init__(self, db: AsyncIOMotorDatabase[Any]) -> None:
        self._col = db.invoices

    async def list_all(self) -> list[dict[str, Any]]:
        cursor = self._col.find({}, {"_id": 0}).sort("invoice_number", 1)
        return [doc async for doc in cursor]

    async def get_by_number(self, invoice_number: str) -> dict[str, Any] | None:
        return await self._col.find_one(
            {"invoice_number": invoice_number}, {"_id": 0}
        )

    async def list_by_customer(self, customer_id: str) -> list[dict[str, Any]]:
        cursor = self._col.find({"customer_id": customer_id}, {"_id": 0}).sort(
            "invoice_number", 1
        )
        return [doc async for doc in cursor]

    async def replace_all(self, docs: list[dict[str, Any]]) -> int:
        await self._col.delete_many({})
        if not docs:
            return 0
        result = await self._col.insert_many(docs)
        return len(result.inserted_ids)

    async def delete_all(self) -> int:
        result = await self._col.delete_many({})
        return result.deleted_count

    async def count(self) -> int:
        return await self._col.count_documents({})
