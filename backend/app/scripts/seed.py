"""Seed MongoDB from ./data.

Usage (from backend/):
    python -m app.scripts.seed
"""

from __future__ import annotations

import asyncio
import sys

from app.config import get_settings
from app.db import close_client, get_db
from app.services.seed import seed_from_data


async def main() -> int:
    settings = get_settings()
    db = get_db(settings)
    counts = await seed_from_data(db, settings=settings, clear_runtime=True)
    print("Seed complete:")
    for key, value in sorted(counts.items()):
        print(f"  {key}: {value}")
    await close_client()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
