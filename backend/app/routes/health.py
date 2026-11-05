from __future__ import annotations

from fastapi import APIRouter

from app.clock import today
from app.config import get_settings
from app.models.invoice import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        today=today().isoformat(),
        demo_today=settings.demo_today,
    )
