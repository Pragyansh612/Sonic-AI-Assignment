from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.models.customer import CustomerOut, CustomerUpdateEmail
from app.repositories.customer import CustomerRepository
from app.security import reject_mongo_operators


class CustomerService:
    def __init__(self, db: AsyncIOMotorDatabase[Any]) -> None:
        self._repo = CustomerRepository(db)

    async def list_customers(self) -> list[CustomerOut]:
        docs = await self._repo.list_all()
        return [CustomerOut.model_validate(d) for d in docs]

    async def get_customer(self, customer_id: str) -> CustomerOut:
        doc = await self._repo.get_by_id(customer_id)
        if doc is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Customer {customer_id} not found",
            )
        return CustomerOut.model_validate(doc)

    async def update_email(
        self, customer_id: str, payload: CustomerUpdateEmail
    ) -> CustomerOut:
        reject_mongo_operators(payload.model_dump())
        doc = await self._repo.update_email(
            customer_id, str(payload.contact_email)
        )
        if doc is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Customer {customer_id} not found",
            )
        return CustomerOut.model_validate(doc)
