from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, UploadFile

from app.models.reconciliation import ApproveRequest, ChooseRequest, UploadResponse
from app.rate_limit import limit_upload
from app.routes.deps import DbDep
from app.security import require_admin_token
from app.services.reconciliation_service import ReconciliationService

router = APIRouter(prefix="/reconciliation", tags=["reconciliation"])


@router.post(
    "/upload",
    response_model=UploadResponse,
    dependencies=[Depends(require_admin_token), Depends(limit_upload)],
)
async def upload_statement(
    db: DbDep,
    file: UploadFile = File(...),
) -> dict[str, Any]:
    return await ReconciliationService(db).upload(file)


@router.get("/statements", dependencies=[Depends(require_admin_token)])
async def list_statements(db: DbDep) -> list[dict[str, Any]]:
    return await ReconciliationService(db).list_statements()


@router.get(
    "/statements/{statement_id}",
    dependencies=[Depends(require_admin_token)],
)
async def get_statement(statement_id: str, db: DbDep) -> dict[str, Any]:
    return await ReconciliationService(db).get_statement_detail(statement_id)


@router.post(
    "/suggestions/{suggestion_id}/approve",
    dependencies=[Depends(require_admin_token)],
)
async def approve_suggestion(
    suggestion_id: str,
    payload: ApproveRequest,
    db: DbDep,
) -> dict[str, Any]:
    return await ReconciliationService(db).approve(
        suggestion_id,
        invoice_numbers=payload.invoice_numbers,
        tds_mode=payload.tds_mode,
    )


@router.post(
    "/suggestions/{suggestion_id}/reject",
    dependencies=[Depends(require_admin_token)],
)
async def reject_suggestion(suggestion_id: str, db: DbDep) -> dict[str, Any]:
    return await ReconciliationService(db).reject(suggestion_id)


@router.post(
    "/suggestions/{suggestion_id}/choose",
    dependencies=[Depends(require_admin_token)],
)
async def choose_suggestion(
    suggestion_id: str,
    payload: ChooseRequest,
    db: DbDep,
) -> dict[str, Any]:
    return await ReconciliationService(db).choose(
        suggestion_id, payload.invoice_numbers
    )
