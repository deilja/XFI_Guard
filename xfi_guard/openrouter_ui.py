"""OpenRouter UI compatibility API."""
from __future__ import annotations
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

def openrouter_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🟣 OpenRouter")],
            [KeyboardButton(text="🔄 Синхронизировать AI")],
            [KeyboardButton(text="🧪 Проверить OpenRouter")],
            [KeyboardButton(text="🧩 Модели OpenRouter")],
            [KeyboardButton(text="⬅️ Главное меню")],
        ], resize_keyboard=True, is_persistent=True,
    )

def install_openrouter_handlers(dp) -> None:
    return None
