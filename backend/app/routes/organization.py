from __future__ import annotations

from fastapi import APIRouter, Depends

from app.models.organization import OrganizationOut
from app.routes.deps import DbDep
from app.security import require_admin_token
from app.services.organization import OrganizationService

router = APIRouter(prefix="/organization", tags=["organization"], dependencies=[Depends(require_admin_token)])


@router.get("", response_model=OrganizationOut)
async def get_organization(db: DbDep) -> OrganizationOut:
    return await OrganizationService(db).get()
