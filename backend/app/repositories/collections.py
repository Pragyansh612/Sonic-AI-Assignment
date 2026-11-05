from __future__ import annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ReturnDocument


class CollectionsRepository:
    def __init__(self, db: AsyncIOMotorDatabase[Any]) -> None:
        self.db = db
        self.conversations = db.conversations
        self.messages = db.messages
        self.locks = db.job_locks

    async def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        return await self.conversations.find_one(
            {"conversation_id": conversation_id}, {"_id": 0}
        )

    async def find_by_customer(self, customer_id: str) -> dict[str, Any] | None:
        return await self.conversations.find_one(
            {"customer_id": customer_id, "kind": {"$ne": "unknown"}},
            {"_id": 0},
            sort=[("updated_at", -1)],
        )

    async def upsert_conversation(self, doc: dict[str, Any]) -> None:
        await self.conversations.update_one(
            {"conversation_id": doc["conversation_id"]},
            {"$set": doc},
            upsert=True,
        )

    async def list_conversations(
        self, *, status: str | None = None
    ) -> list[dict[str, Any]]:
        query: dict[str, Any] = {}
        if status:
            query["status"] = status
        cursor = self.conversations.find(query, {"_id": 0}).sort("updated_at", -1)
        return [d async for d in cursor]

    async def list_needs_attention(self) -> list[dict[str, Any]]:
        cursor = self.conversations.find(
            {"status": "needs_attention"}, {"_id": 0}
        ).sort("updated_at", -1)
        return [d async for d in cursor]

    async def insert_message(self, doc: dict[str, Any]) -> bool:
        """Insert message; return False if duplicate message_id."""
        try:
            await self.messages.insert_one(doc)
            return True
        except Exception:
            existing = await self.messages.find_one(
                {"message_id": doc["message_id"]}, {"_id": 0}
            )
            return existing is None

    async def message_exists(self, message_id: str) -> bool:
        return (
            await self.messages.find_one({"message_id": message_id}, {"_id": 1})
            is not None
        )

    async def message_processed(self, message_id: str) -> bool:
        """True once an inbound message was fully handled (retries are not duplicates)."""
        doc = await self.messages.find_one({"message_id": message_id}, {"processed": 1})
        return doc is not None and doc.get("processed", True) is True

    async def mark_message_processed(self, message_id: str) -> None:
        await self.messages.update_one(
            {"message_id": message_id}, {"$set": {"processed": True}}
        )

    async def list_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        cursor = self.messages.find(
            {"conversation_id": conversation_id}, {"_id": 0}
        ).sort("created_at", 1)
        return [d async for d in cursor]

    async def update_conversation(
        self, conversation_id: str, **fields: Any
    ) -> dict[str, Any] | None:
        return await self.conversations.find_one_and_update(
            {"conversation_id": conversation_id},
            {"$set": fields},
            projection={"_id": 0},
            return_document=ReturnDocument.AFTER,
        )

    async def acquire_lock(self, name: str, owner: str, ttl_seconds: int = 120) -> bool:
        from app.clock import utc_now
        from datetime import timedelta

        now = utc_now()
        expires = (now + timedelta(seconds=ttl_seconds)).isoformat()
        existing = await self.locks.find_one({"_id": name})
        if existing and existing.get("expires_at", "") > now.isoformat():
            return False
        await self.locks.update_one(
            {"_id": name},
            {"$set": {"owner": owner, "expires_at": expires}},
            upsert=True,
        )
        return True

    async def release_lock(self, name: str, owner: str) -> None:
        await self.locks.delete_one({"_id": name, "owner": owner})
