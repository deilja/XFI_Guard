"""Telegram UI manager.

XFI Guard uses one message as the active menu. Menus are rendered as inline
buttons, while existing message handlers remain compatible through a callback
bridge. Every submenu gets ◀️ Назад and 🏠 Главная navigation.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any, ClassVar

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Update

_original_send_message = Bot.send_message
_original_start_polling = Dispatcher.start_polling
_last_menu: dict[str, int] = {}
_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
_installed = False
_bridge_installed: set[int] = set()


def _chat_key(chat_id: int | str, thread_id: int | None = None) -> str:
    return f"{chat_id}:{thread_id or 0}"


def _is_main_menu(texts: list[str]) -> bool:
    return "📊 Статус" in texts and "🚫 Блокировка IP" in texts


def _back_target(texts: list[str]) -> str:
    ai_markers = {
        "🧠 Модель Gemini", "🧠 Модель Groq", "📋 Модели Gemini",
        "📋 Модели Groq", "🔑 Ключ Gemini", "🔑 Ключ Groq",
        "✏️ Своя модель Gemini", "✏️ Своя модель Groq",
    }
    return "⬅️ AI" if any(x in ai_markers for x in texts) else "⬅️ Главное меню"


class InlineMenuMarkup(InlineKeyboardMarkup):
    """Compatibility replacement for ReplyKeyboardMarkup used by bot.py."""

    xfi_inline_menu: ClassVar[bool] = True

    def __init__(self, *, keyboard: list[list[Any]], **_: Any):
        texts: list[str] = []
        for row in keyboard:
            for item in row:
                texts.append(getattr(item, "text", None) or str(item))

        cleaned = [
            [getattr(item, "text", None) or str(item) for item in row]
            for row in keyboard
        ]
        cleaned = [
            [x for x in row if x not in {"⬅️ Главное меню", "⬅️ AI"}]
            for row in cleaned
        ]
        cleaned = [row for row in cleaned if row]

        if not _is_main_menu(texts):
            cleaned.append(["◀️ Назад", "🏠 Главная"])

        rows: list[list[InlineKeyboardButton]] = []
        back_target = _back_target(texts)
        for row in cleaned:
            buttons: list[InlineKeyboardButton] = []
            for text in row:
                callback_data = text
                if text == "◀️ Назад":
                    callback_data = back_target
                elif text == "🏠 Главная":
                    callback_data = "⬅️ Главное меню"
                buttons.append(InlineKeyboardButton(text=text, callback_data=callback_data[:64]))
            if buttons:
                rows.append(buttons)
        super().__init__(inline_keyboard=rows)


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


async def _safe_callback_answer(callback: CallbackQuery) -> bool:
    """Acknowledge a callback without letting an expired query crash the bot.

    Telegram callback queries have a short acknowledgement window. A delayed
    or replayed button can legitimately produce ``query is too old`` / invalid
    query errors. The menu action itself should still be processed.
    """
    try:
        await callback.answer()
        return True
    except TelegramBadRequest as exc:
        message = str(exc).lower()
        if "query is too old" in message or "response timeout expired" in message or "query id is invalid" in message:
            return False
        raise


async def _callback_bridge(callback: CallbackQuery, dispatcher: Dispatcher) -> None:
    """Delete the exact clicked menu, acknowledge it, then route its callback as a message."""
    if not callback.message or not callback.data:
        await _safe_callback_answer(callback)
        return

    # Acknowledge as early as possible. Previously this happened only after the
    # delete-message API call, so a slow Telegram/API response could make the
    # callback query expire before acknowledgement.
    await _safe_callback_answer(callback)

    bot = callback.bot
    message = callback.message
    key = _chat_key(message.chat.id, getattr(message, "message_thread_id", None))

    # Always delete the exact Telegram message containing the clicked button.
    # Do not rely only on _last_menu: this also works after a restart, when the
    # in-memory menu registry is empty.
    async with _locks[key]:
        try:
            await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
        except Exception:
            pass
        if _last_menu.get(key) == message.message_id:
            _last_menu.pop(key, None)

    synthetic_message = message.model_copy(
        update={"text": callback.data, "from_user": callback.from_user}
    )
    update = Update(update_id=0, message=synthetic_message)
    await dispatcher.feed_update(bot, update)


async def _register_callback_bridge(dispatcher: Dispatcher) -> None:
    """Register the async callback handler exactly once for this dispatcher."""
    marker = id(dispatcher)
    if marker in _bridge_installed:
        return

    async def bridge_handler(callback: CallbackQuery) -> None:
        await _callback_bridge(callback, dispatcher)

    dispatcher.callback_query.register(bridge_handler)
    _bridge_installed.add(marker)


async def _start_polling_with_bridge(self: Dispatcher, *args: Any, **kwargs: Any):
    await _register_callback_bridge(self)
    return await _original_start_polling(self, *args, **kwargs)


def install() -> None:
    global _installed
    if _installed:
        return
    Bot.send_message = _send_message_with_menu_cleanup  # type: ignore[method-assign]
    Dispatcher.start_polling = _start_polling_with_bridge  # type: ignore[method-assign]
    _installed = True


install()
