"""Lightweight per-user rate limiting for Telegram handlers."""
from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject


class RateLimitMiddleware(BaseMiddleware):
    """Allow at most ``rate`` events per user during ``period`` seconds."""

    def __init__(self, rate: int = 2, period: float = 1.0) -> None:
        self.rate = max(1, int(rate))
        self.period = max(0.1, float(period))
        self._events: dict[int, deque[float]] = defaultdict(deque)

    def _user_id(self, event: TelegramObject) -> int | None:
        if isinstance(event, Message):
            return event.from_user.id if event.from_user else None
        if isinstance(event, CallbackQuery):
            return event.from_user.id if event.from_user else None
        return None

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user_id = self._user_id(event)
        if user_id is None:
            return await handler(event, data)

        now = time.monotonic()
        queue = self._events[user_id]
        cutoff = now - self.period
        while queue and queue[0] <= cutoff:
            queue.popleft()

        if len(queue) >= self.rate:
            if isinstance(event, CallbackQuery):
                await event.answer("Слишком часто. Повторите через секунду.", show_alert=False)
            elif isinstance(event, Message):
                await event.answer("⏱ Слишком много запросов. Повторите через секунду.")
            return None

        queue.append(now)
        return await handler(event, data)
