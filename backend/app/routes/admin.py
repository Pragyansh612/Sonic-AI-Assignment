from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.models.invoice import ResetRequest, ResetResponse
from app.routes.deps import DbDep
from app.security import require_admin_token
from app.services.seed import reset_demo_data

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post(
    "/reset",
    response_model=ResetResponse,
    dependencies=[Depends(require_admin_token)],
)
async def reset_demo(payload: ResetRequest, db: DbDep) -> ResetResponse:
    """Restore original ./data and clear conversations, payments, bank data."""
    if payload.confirm != "RESET":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Confirmation required: set confirm to "RESET"',
        )
    counts = await reset_demo_data(db)
    return ResetResponse(
        ok=True,
        message="Demo data restored from ./data; conversations and payments cleared.",
        counts=counts,
    )
