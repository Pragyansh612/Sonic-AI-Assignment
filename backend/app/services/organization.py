from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.models.organization import OrganizationOut
from app.repositories.organization import OrganizationRepository


class OrganizationService:
    def __init__(self, db: AsyncIOMotorDatabase[Any]) -> None:
        self._repo = OrganizationRepository(db)

    async def get(self) -> OrganizationOut:
        doc = await self._repo.get()
        if doc is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Organization not seeded. Run: python -m app.scripts.seed",
            )
        return OrganizationOut.model_validate(doc)
