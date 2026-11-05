from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from app.models.invoice import InvoiceOut
from app.routes.deps import DbDep
from app.security import require_admin_token
from app.services.invoice_service import InvoiceService
from app.services.reconciliation_service import ReconciliationService

router = APIRouter(prefix="/invoices", tags=["invoices"], dependencies=[Depends(require_admin_token)])


@router.get("", response_model=list[InvoiceOut])
async def list_invoices(
    db: DbDep,
    customer_id: str | None = Query(default=None),
    status: str | None = Query(default=None, description="draft | sent | paid"),
    overdue_only: bool = Query(default=False),
) -> list[InvoiceOut]:
    return await InvoiceService(db).list_invoices(
        customer_id=customer_id,
        status_filter=status,
        overdue_only=overdue_only,
    )


@router.get(
    "/open",
    dependencies=[Depends(require_admin_token)],
)
async def list_open_invoices(db: DbDep) -> list[dict[str, Any]]:
    """Open (sent, unpaid) invoices for the reconciliation choose dropdown."""
    return await ReconciliationService(db).list_open_invoices()


@router.get("/{invoice_number}", response_model=InvoiceOut)
async def get_invoice(invoice_number: str, db: DbDep) -> InvoiceOut:
    return await InvoiceService(db).get_invoice(invoice_number)
