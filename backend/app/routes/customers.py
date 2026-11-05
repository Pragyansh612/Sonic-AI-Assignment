from __future__ import annotations

from fastapi import APIRouter, Depends

from app.models.customer import CustomerOut, CustomerUpdateEmail
from app.routes.deps import DbDep
from app.security import require_admin_token
from app.services.customers import CustomerService

router = APIRouter(prefix="/customers", tags=["customers"])


@router.get("", response_model=list[CustomerOut])
async def list_customers(db: DbDep) -> list[CustomerOut]:
    return await CustomerService(db).list_customers()


@router.get("/{customer_id}", response_model=CustomerOut)
async def get_customer(customer_id: str, db: DbDep) -> CustomerOut:
    return await CustomerService(db).get_customer(customer_id)


@router.patch(
    "/{customer_id}",
    response_model=CustomerOut,
    dependencies=[Depends(require_admin_token)],
)
async def update_customer_email(
    customer_id: str,
    payload: CustomerUpdateEmail,
    db: DbDep,
) -> CustomerOut:
    return await CustomerService(db).update_email(customer_id, payload)
