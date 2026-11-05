"""Simple in-process rate limiter for expensive endpoints."""

from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status


class SlidingWindowLimiter:
    def __init__(self, *, max_calls: int, window_seconds: float) -> None:
        self.max_calls = max_calls
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        now = time.monotonic()
        q = self._hits[key]
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.max_calls:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded; try again shortly",
            )
        q.append(now)


upload_limiter = SlidingWindowLimiter(max_calls=10, window_seconds=60.0)


async def limit_upload(request: Request) -> None:
    client = request.client.host if request.client else "unknown"
    upload_limiter.check(f"upload:{client}")
