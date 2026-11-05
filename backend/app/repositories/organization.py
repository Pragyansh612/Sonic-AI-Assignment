from __future__ import annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase


class OrganizationRepository:
    def __init__(self, db: AsyncIOMotorDatabase[Any]) -> None:
        self._col = db.organization

    async def get(self) -> dict[str, Any] | None:
        return await self._col.find_one({"_id": "singleton"}, {"_id": 0})

    async def replace(self, doc: dict[str, Any]) -> None:
        await self._col.replace_one(
            {"_id": "singleton"},
            {"_id": "singleton", **doc},
            upsert=True,
        )

    async def delete_all(self) -> int:
        result = await self._col.delete_many({})
        return result.deleted_count
