"""MongoDB connection via Motor."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.config import Settings, get_settings

_client: AsyncIOMotorClient[Any] | None = None


def get_client(settings: Settings | None = None) -> AsyncIOMotorClient[Any]:
    global _client
    if _client is None:
        settings = settings or get_settings()
        _client = AsyncIOMotorClient(settings.mongodb_uri)
    return _client


def get_db(settings: Settings | None = None) -> AsyncIOMotorDatabase[Any]:
    settings = settings or get_settings()
    return get_client(settings)[settings.mongodb_db]


async def close_client() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None


async def ensure_indexes(db: AsyncIOMotorDatabase[Any] | None = None) -> None:
    """Create required indexes (idempotent)."""
    database = get_db() if db is None else db

    await database.invoices.create_index("invoice_number", unique=True)
    await database.invoices.create_index("customer_id")
    await database.invoices.create_index([("status", 1), ("due_date", 1)])

    await database.customers.create_index("customer_id", unique=True)
    await database.customers.create_index("contact_email")

    await database.conversations.create_index("customer_id")
    await database.conversations.create_index("conversation_id", unique=True)
    await database.conversations.create_index("status")

    await database.messages.create_index("message_id", unique=True)
    await database.messages.create_index("conversation_id")

    await database.payments.create_index("payment_id", unique=True)
    await database.payments.create_index("invoice_numbers")
    await database.payments.create_index("bank_transaction_id", unique=True, sparse=True)

    await database.bank_statements.create_index("statement_id", unique=True)
    await database.bank_transactions.create_index("transaction_id", unique=True)
    await database.bank_transactions.create_index("statement_id")
    await database.bank_transactions.create_index("fingerprint")
    await database.bank_transactions.create_index(
        [("fingerprint", 1), ("status", 1)]
    )

    await database.match_suggestions.create_index("suggestion_id", unique=True)
    await database.match_suggestions.create_index("transaction_id", unique=True)
    await database.match_suggestions.create_index("status")

    await database.audit_log.create_index("created_at")
    await database.audit_log.create_index("action")


async def get_database() -> AsyncGenerator[AsyncIOMotorDatabase[Any], None]:
    yield get_db()
