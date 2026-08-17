"""Управление меню Telegram: удаляет предыдущее меню перед показом нового."""
from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

from aiogram import Bot
from aiogram.types import ReplyKeyboardMarkup


_original_send_message = Bot.send_message
_last_menu: dict[str, int] = {}
_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
_installed = False


def _chat_key(chat_id: int | str, thread_id: int | None = None) -> str:
    return f"{chat_id}:{thread_id or 0}"


async def _delete_previous_menu(bot: Bot, key: str) -> None:
    message_id = _last_menu.pop(key, None)
    if message_id is None:
        return
    try:
        await bot.delete_message(chat_id=key.split(":", 1)[0], message_id=message_id)
    except Exception:
        # Сообщение могло быть удалено вручную, устареть или стать недоступным.
        pass


async def _send_message_with_menu_cleanup(self: Bot, chat_id: int | str, text: str, *args: Any, **kwargs: Any):
    thread_id = kwargs.get("message_thread_id")
    key = _chat_key(chat_id, thread_id)
    markup = kwargs.get("reply_markup")

    async with _locks[key]:
        # Перед переходом на любой новый экран удаляем предыдущее меню.
        await _delete_previous_menu(self, key)
        result = await _original_send_message(self, chat_id, text, *args, **kwargs)

        # Запоминаем только сообщение с обычной ReplyKeyboardMarkup.
        # Inline-кнопки и сообщения без клавиатуры не считаются меню.
        if isinstance(markup, ReplyKeyboardMarkup) and getattr(result, "message_id", None):
            _last_menu[key] = result.message_id

        return result


def install() -> None:
    global _installed
    if _installed:
        return
    Bot.send_message = _send_message_with_menu_cleanup  # type: ignore[method-assign]
    _installed = True


install()
