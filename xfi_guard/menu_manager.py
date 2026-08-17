"""Telegram UI manager.

XFI Guard uses one message as the active menu. Menus are rendered as inline
buttons, while the existing message handlers are kept compatible by bridging
callback queries back into synthetic messages with the button text.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Update

_original_send_message = Bot.send_message
_original_start_polling = Dispatcher.start_polling
_last_menu: dict[str, int] = {}
_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
_installed = False
_bridge_installed: set[int] = set()


def _chat_key(chat_id: int | str, thread_id: int | None = None) -> str:
    return f"{chat_id}:{thread_id or 0}"


class InlineMenuMarkup(InlineKeyboardMarkup):
    """Compatibility replacement for ReplyKeyboardMarkup used by bot.py."""

    xfi_inline_menu = True

    def __init__(self, *, keyboard: list[list[Any]], **_: Any):
        rows: list[list[InlineKeyboardButton]] = []
        for row in keyboard:
            buttons: list[InlineKeyboardButton] = []
            for item in row:
                text = getattr(item, "text", None) or str(item)
                buttons.append(InlineKeyboardButton(text=text, callback_data=text[:64]))
            if buttons:
                rows.append(buttons)
        super().__init__(inline_keyboard=rows)


# __init__.py imports menu_manager before bot.py imports ReplyKeyboardMarkup.
# Therefore existing kb() functions automatically create inline keyboards.
import aiogram.types as _aiogram_types
_aiogram_types.ReplyKeyboardMarkup = InlineMenuMarkup


async def _delete_previous_menu(bot: Bot, key: str) -> None:
    message_id = _last_menu.pop(key, None)
    if message_id is None:
        return
    try:
        await bot.delete_message(chat_id=key.split(":", 1)[0], message_id=message_id)
    except Exception:
        pass


async def _send_message_with_menu_cleanup(self: Bot, chat_id: int | str, text: str, *args: Any, **kwargs: Any):
    thread_id = kwargs.get("message_thread_id")
    key = _chat_key(chat_id, thread_id)
    markup = kwargs.get("reply_markup")

    async with _locks[key]:
        await _delete_previous_menu(self, key)
        result = await _original_send_message(self, chat_id, text, *args, **kwargs)
        if getattr(markup, "xfi_inline_menu", False) and getattr(result, "message_id", None):
            _last_menu[key] = result.message_id
        return result


async def _callback_bridge(callback: CallbackQuery, dispatcher: Dispatcher) -> None:
    """Turn an inline-button press into the existing message-handler event."""
    if not callback.message or not callback.data:
        await callback.answer()
        return

    await callback.answer()
    bot = callback.bot
    key = _chat_key(callback.message.chat.id, getattr(callback.message, "message_thread_id", None))
    await _delete_previous_menu(bot, key)

    synthetic_message = callback.message.model_copy(
        update={"text": callback.data, "from_user": callback.from_user}
    )
    update = Update(update_id=0, message=synthetic_message)
    await dispatcher.feed_update(bot, update)


async def _start_polling_with_bridge(self: Dispatcher, *args: Any, **kwargs: Any):
    marker = id(self)
    if marker not in _bridge_installed:
        self.callback_query.register(lambda q: _callback_bridge(q, self))
        _bridge_installed.add(marker)
    return await _original_start_polling(self, *args, **kwargs)


def install() -> None:
    global _installed
    if _installed:
        return
    Bot.send_message = _send_message_with_menu_cleanup  # type: ignore[method-assign]
    Dispatcher.start_polling = _start_polling_with_bridge  # type: ignore[method-assign]
    _installed = True


install()
