"""Modern AI API-key management UI for XFI Guard."""
from __future__ import annotations

import os
from aiogram import F, Dispatcher
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from .ai_store import load, save


class AIKeyState(StatesGroup):
    waiting = State()


def _kb(rows):
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=x) for x in row] for row in rows], resize_keyboard=True, is_persistent=True)


def _admin(message) -> bool:
    ids = {int(v) for v in os.getenv("XFI_GUARD_ADMIN_IDS", "").split(",") if v.strip().isdigit()}
    return bool(message.from_user and message.from_user.id in ids)


def _mask(value: str) -> str:
    value = value or ""
    if len(value) < 10:
        return "••••••••" if value else "не задан"
    return value[:4] + "••••••••" + value[-4:]


async def _delete_secret_message(message) -> None:
    try:
        await message.delete()
    except Exception:
        # Telegram may reject deletion because of permissions, age, or chat type.
        # Never expose the key in a replacement message.
        pass


def install_ai_key_handlers(dp: Dispatcher) -> None:
    if getattr(dp, "_xfi_ai_keys_installed", False): return
    dp._xfi_ai_keys_installed = True

    @dp.message(F.text == "🔑 API ключи")
    async def keys_menu(message, state: FSMContext):
        if not _admin(message): return
        await state.clear(); cfg = load()
        await message.answer(
            "🔑 API КЛЮЧИ\n\nКлючи хранятся локально в /var/lib/xfi-guard/ai.json с правами 600.\n\n"
            f"🟣 Gemini: {_mask(cfg.get('gemini_key') or os.getenv('GEMINI_API_KEY', ''))}\n"
            f"🟢 Groq: {_mask(cfg.get('groq_key') or os.getenv('GROQ_API_KEY', ''))}\n"
            f"🔵 OpenRouter: {_mask(cfg.get('openrouter_key') or os.getenv('OPENROUTER_API_KEY', ''))}\n"
            f"🟠 RouterAI: {_mask(cfg.get('routerai_key') or os.getenv('ROUTERAI_API_KEY', ''))}",
            reply_markup=_kb([["🔑 Gemini", "🔑 Groq"], ["🔑 OpenRouter", "🔑 RouterAI"], ["🧩 API модели"], ["⬅️ AI"]]),
        )

    async def ask_key(message, state: FSMContext, provider: str):
        if not _admin(message): return
        await state.set_state(AIKeyState.waiting); await state.update_data(provider=provider)
        await message.answer(f"🔑 {provider.upper()} API\n\nОтправьте API key одним сообщением.\nПосле сохранения это сообщение будет удалено, если Telegram разрешит удаление.\n\nДля отмены: ⬅️ AI", reply_markup=_kb([["⬅️ AI"]]))

    for label, provider in (("🔑 Gemini", "gemini"), ("🔑 Groq", "groq"), ("🔑 OpenRouter", "openrouter"), ("🔑 RouterAI", "routerai")):
        @dp.message(F.text == label)
        async def provider_key(message, state, _provider=provider): await ask_key(message, state, _provider)

    @dp.message(AIKeyState.waiting)
    async def receive_key(message, state: FSMContext):
        if not _admin(message): return
        text = (message.text or "").strip()
        if not text or text.startswith("/"): return
        data = await state.get_data(); provider = data.get("provider")
        if provider not in {"gemini", "groq", "openrouter", "routerai"}:
            await state.clear(); return
        cfg = load(); cfg[f"{provider}_key"] = text
        try:
            save(cfg)
        except Exception:
            await state.clear(); await _delete_secret_message(message)
            await message.answer("❌ Не удалось сохранить API key. Исходное сообщение с ключом удалено, если Telegram разрешил удаление.", reply_markup=_kb([["🔑 API ключи", "🧩 API модели"], ["⬅️ AI"]]))
            return
        await state.clear()
        await _delete_secret_message(message)
        await message.answer(f"✅ {provider.upper()} API key сохранён. Исходное сообщение с ключом удалено, если Telegram разрешил удаление.\n\nОткройте 🧩 API модели для выбора и проверки модели.", reply_markup=_kb([["🔑 API ключи", "🧩 API модели"], ["⬅️ AI"]]))
