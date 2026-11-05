from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.db import get_db


def database_dep() -> AsyncIOMotorDatabase[Any]:
    return get_db()


DbDep = Annotated[AsyncIOMotorDatabase[Any], Depends(database_dep)]
