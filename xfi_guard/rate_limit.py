"""Small in-memory rate limiter for the administrative Telegram bot."""
from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware


class RateLimitMiddleware(BaseMiddleware):
    """Limit updates per Telegram user without adding a Redis dependency."""

    def __init__(self, rate: float = 2.0, burst: int = 2) -> None:
        if rate <= 0 or burst < 1:
            raise ValueError("rate must be > 0 and burst must be >= 1")
        self.rate = float(rate)
        self.burst = int(burst)
        self._hits: dict[int, deque[float]] = defaultdict(deque)

    def _allowed(self, user_id: int) -> bool:
        now = time.monotonic()
        window = self.burst / self.rate
        hits = self._hits[user_id]
        while hits and now - hits[0] >= window:
            hits.popleft()
        if len(hits) >= self.burst:
            return False
        hits.append(now)
        return True

    async def __call__(
        self,
        handler: Callable[[Any, dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        user_id = getattr(user, "id", None)
        if user_id is None or self._allowed(int(user_id)):
            return await handler(event, data)
        answer = getattr(event, "answer", None)
        if callable(answer):
            try:
                await answer("Слишком часто. Повторите через секунду.", show_alert=True)
            except Exception:
                pass
        return None
