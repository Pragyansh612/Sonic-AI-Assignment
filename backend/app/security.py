"""Auth helpers and Mongo operator-injection guards."""

from __future__ import annotations

from typing import Any, Mapping

from fastapi import Header, HTTPException, status

from app.config import get_settings


def reject_mongo_operators(payload: Mapping[str, Any], *, path: str = "") -> None:
    """
    Reject keys that start with '$' or contain '.' to prevent operator injection
    when user input is merged into Mongo queries/updates.
    """
    for key, value in payload.items():
        full = f"{path}.{key}" if path else key
        if key.startswith("$") or "." in key:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Illegal key in request body: {full}",
            )
        if isinstance(value, Mapping):
            reject_mongo_operators(value, path=full)
        elif isinstance(value, list):
            for i, item in enumerate(value):
                if isinstance(item, Mapping):
                    reject_mongo_operators(item, path=f"{full}[{i}]")


async def require_admin_token(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> None:
    settings = get_settings()
    if not x_admin_token or x_admin_token != settings.admin_api_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing admin token",
        )
