from __future__ import annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ReturnDocument


class CustomerRepository:
    def __init__(self, db: AsyncIOMotorDatabase[Any]) -> None:
        self._col = db.customers

    async def list_all(self) -> list[dict[str, Any]]:
        cursor = self._col.find({}, {"_id": 0}).sort("customer_id", 1)
        return [doc async for doc in cursor]

    async def get_by_id(self, customer_id: str) -> dict[str, Any] | None:
        return await self._col.find_one({"customer_id": customer_id}, {"_id": 0})

    async def update_email(self, customer_id: str, contact_email: str) -> dict[str, Any] | None:
        result = await self._col.find_one_and_update(
            {"customer_id": customer_id},
            {"$set": {"contact_email": contact_email}},
            projection={"_id": 0},
            return_document=ReturnDocument.AFTER,
        )
        return result

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
