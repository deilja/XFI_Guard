"""OpenRouter Telegram UI and model synchronization for XFI Guard."""
from __future__ import annotations

import asyncio
import json
import os
from urllib import request

from aiogram import F, Dispatcher
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from .ai import AIAnalyzer
from .ai_store import load, save


class OpenRouterStates(StatesGroup):
    key = State()
    model = State()


def _admin(message) -> bool:
    ids = {int(v) for v in os.getenv("XFI_GUARD_ADMIN_IDS", "").split(",") if v.strip().isdigit()}
    return bool(message.from_user and message.from_user.id in ids)


def _kb(rows):
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=x) for x in row] for row in rows],
        resize_keyboard=True,
        is_persistent=True,
    )


def _mask(value: str) -> str:
    if not value:
        return "не настроен"
    return value[:4] + "…" + value[-4:] if len(value) >= 8 else "настроен"


def openrouter_menu():
    return _kb([
        ["🟣 OpenRouter", "🔑 Ключ OpenRouter"],
        ["🧠 Модель OpenRouter", "📋 Модели OpenRouter"],
        ["🔄 Синхронизировать AI", "🧪 Проверить OpenRouter"],
        ["⬅️ AI"],
    ])


def _fetch_models(key: str) -> list[str]:
    req = request.Request(
        "https://openrouter.ai/api/v1/models",
        headers={"Authorization": f"Bearer {key}", "User-Agent": "XFI-Guard/1.2"},
    )
    with request.urlopen(req, timeout=20) as response:
        data = json.loads(response.read().decode())
    models = []
    for item in data.get("data", []) or []:
        model_id = str(item.get("id", "")).strip()
        if model_id:
            models.append(model_id)
    return sorted(set(models))


def _sync() -> dict:
    """Return the current persisted AI settings and validate them through AIAnalyzer."""
    cfg = load()
    analyzer = AIAnalyzer()
    status = analyzer.status()
    cfg["provider"] = status["selected_provider"]
    cfg["openrouter_model"] = status["openrouter_model"]
    cfg["openrouter_models"] = tuple(status["openrouter_models"])
    save(cfg)
    return load()


def install_openrouter_handlers(dp: Dispatcher) -> None:
    if getattr(dp, "_xfi_openrouter_handlers_installed", False):
        return
    dp._xfi_openrouter_handlers_installed = True

    @dp.message(F.text == "🟣 OpenRouter")
    async def select_openrouter(m, state: FSMContext):
        if not _admin(m):
            return
        cfg = load()
        cfg["provider"] = "openrouter"
        save(cfg)
        await state.clear()
        await m.answer("🟣 Активный AI: OpenRouter", reply_markup=openrouter_menu())

    @dp.message(F.text == "🔑 Ключ OpenRouter")
    async def openrouter_key_prompt(m, state: FSMContext):
        if _admin(m):
            await state.set_state(OpenRouterStates.key)
            await m.answer("Введите API-ключ OpenRouter (sk-or-...):", reply_markup=_kb([["❌ Отмена"], ["⬅️ AI"]]))

    @dp.message(OpenRouterStates.key)
    async def openrouter_key_save(m, state: FSMContext):
        if not _admin(m):
            return
        if m.text in {"❌ Отмена", "⬅️ AI"}:
            await state.clear()
            await m.answer("Отменено.", reply_markup=openrouter_menu())
            return
        key = (m.text or "").strip()
        if not key.startswith("sk-or-") or len(key) < 20:
            await m.answer("❌ Неверный формат. OpenRouter API key должен начинаться с sk-or-.")
            return
        cfg = load()
        cfg["openrouter_key"] = key
        cfg["provider"] = "openrouter"
        save(cfg)
        await state.clear()
        await m.answer(f"✅ OpenRouter сохранён: {_mask(key)}", reply_markup=openrouter_menu())

    @dp.message(F.text == "📋 Модели OpenRouter")
    async def openrouter_models(m):
        if not _admin(m):
            return
        key = load().get("openrouter_key", "") or os.getenv("OPENROUTER_API_KEY", "")
        if not key:
            await m.answer("❌ Сначала сохраните ключ OpenRouter.", reply_markup=openrouter_menu())
            return
        try:
            models = await asyncio.to_thread(_fetch_models, key)
            cfg = load()
            cfg["openrouter_models"] = tuple(models[:200])
            save(cfg)
            current = cfg.get("openrouter_model", "openrouter/free")
            await m.answer(
                "📋 OpenRouter API\n\n" + "\n".join(models[:60]) + f"\n\nТекущая: {current}",
                reply_markup=openrouter_menu(),
            )
        except Exception as exc:
            await m.answer(f"❌ OpenRouter API: {type(exc).__name__}: {exc}", reply_markup=openrouter_menu())

    @dp.message(F.text == "🧠 Модель OpenRouter")
    async def openrouter_model_menu(m):
        if not _admin(m):
            return
        cfg = load()
        models = list(cfg.get("openrouter_models") or [])
        if not models:
            models = [cfg.get("openrouter_model", "openrouter/free"), "openrouter/auto"]
        rows = [[f"🟣 {x}" for x in models[i:i + 2]] for i in range(0, min(len(models), 20), 2)]
        rows += [["✏️ Своя модель OpenRouter"], ["📋 Модели OpenRouter"], ["⬅️ AI"]]
        await m.answer(f"Модель OpenRouter: {cfg.get('openrouter_model', '')}", reply_markup=_kb(rows))

    @dp.message(F.text.startswith("🟣 "))
    async def choose_openrouter_model(m):
        if not _admin(m):
            return
        model = (m.text or "").removeprefix("🟣 ").strip()
        if not model or model in {"OpenRouter"}:
            return
        cfg = load()
        cfg["openrouter_model"] = model
        cfg["provider"] = "openrouter"
        save(cfg)
        await m.answer(f"✅ Модель OpenRouter: {model}", reply_markup=openrouter_menu())

    @dp.message(F.text == "✏️ Своя модель OpenRouter")
    async def custom_openrouter_prompt(m, state: FSMContext):
        if _admin(m):
            await state.set_state(OpenRouterStates.model)
            await m.answer("Введите ID модели OpenRouter в формате provider/model:", reply_markup=_kb([["❌ Отмена"], ["⬅️ AI"]]))

    @dp.message(OpenRouterStates.model)
    async def custom_openrouter_save(m, state: FSMContext):
        if not _admin(m):
            return
        if m.text in {"❌ Отмена", "⬅️ AI"}:
            await state.clear()
            await m.answer("Отменено.", reply_markup=openrouter_menu())
            return
        model = (m.text or "").strip()
        if "/" not in model:
            await m.answer("❌ ID должен быть в формате provider/model.")
            return
        cfg = load()
        cfg["openrouter_model"] = model
        cfg["provider"] = "openrouter"
        save(cfg)
        await state.clear()
        await m.answer(f"✅ Модель OpenRouter: {model}", reply_markup=openrouter_menu())

    @dp.message(F.text == "🔄 Синхронизировать AI")
    async def sync_ai(m):
        if not _admin(m):
            return
        cfg = await asyncio.to_thread(_sync)
        analyzer = AIAnalyzer()
        status = analyzer.status()
        await m.answer(
            "🔄 AI синхронизирован\n\n"
            f"Провайдер: {cfg.get('provider', 'gemini')}\n"
            f"OpenRouter key: {_mask(cfg.get('openrouter_key', ''))}\n"
            f"OpenRouter model: {cfg.get('openrouter_model', '')}\n"
            f"Доступно: {', '.join(status['available_providers']) or 'нет'}",
            reply_markup=openrouter_menu(),
        )

    @dp.message(F.text == "🧪 Проверить OpenRouter")
    async def test_openrouter(m):
        if not _admin(m):
            return
        analyzer = AIAnalyzer(provider="openrouter")
        if "openrouter" not in analyzer.available_providers():
            await m.answer("❌ OpenRouter не настроен. Сохраните ключ.", reply_markup=openrouter_menu())
            return
        result = await asyncio.to_thread(
            analyzer.analyze,
            {"event_type": "health_check", "severity": "info", "message": "Проверка OpenRouter XFI Guard. Ответь: OpenRouter работает."},
            False,
        )
        if result:
            await m.answer("✅ OpenRouter работает\n\n" + result[:3000], reply_markup=openrouter_menu())
        else:
            await m.answer("❌ OpenRouter не ответил\n\n" + (analyzer.last_error or "неизвестная ошибка"), reply_markup=openrouter_menu())
