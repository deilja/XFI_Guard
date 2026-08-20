"""AI Telegram UI handlers for XFI Guard."""
from __future__ import annotations

import asyncio
import json
import os
from urllib import request

from aiogram import F, Dispatcher
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from .ai_store import load, save
from .ai import AIAnalyzer
from .ai_health import run_health_check
from .ai_health_dashboard import dashboard_text


class AISetupStates(StatesGroup):
    gemini_key = State()
    groq_key = State()
    gemini_model = State()
    groq_model = State()


def _kb(rows):
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=x) for x in row] for row in rows],
        resize_keyboard=True,
        is_persistent=True,
    )


def _admin(message) -> bool:
    ids = {int(v) for v in os.getenv("XFI_GUARD_ADMIN_IDS", "").split(",") if v.strip().isdigit()}
    return bool(message.from_user and message.from_user.id in ids)


def _mask(value: str) -> str:
    if not value:
        return "не настроен"
    return value[:4] + "…" + value[-4:] if len(value) >= 8 else "настроен"


def _ai_menu():
    return _kb([
        ["🟢 Gemini", "🔵 Groq"], ["🔀 Выбрать AI"],
        ["🔑 Ключ Gemini", "🔑 Ключ Groq"], ["🧠 Модель Gemini", "🧠 Модель Groq"],
        ["📋 Модели Gemini", "📋 Модели Groq"],
        ["✏️ Своя модель Gemini", "✏️ Своя модель Groq"],
        ["🧪 Проверить AI", "📊 Диагностика AI"], ["ℹ️ Статус AI"], ["⬅️ Главное меню"],
    ])


def _model_menu(provider: str, models: list[str]):
    rows = [[f"🧠 {x}" for x in models[i:i + 2]] for i in range(0, len(models), 2)]
    rows += [[f"🔄 Получить модели {provider} API"], [f"✏️ Своя модель {provider}"], ["⬅️ AI"]]
    return _kb(rows)


def _fetch_groq_models(key: str) -> list[str]:
    req = request.Request("https://api.groq.com/openai/v1/models", headers={"Authorization": f"Bearer {key}"})
    with request.urlopen(req, timeout=15) as response:
        data = json.loads(response.read().decode())
    return sorted({str(x.get("id")) for x in data.get("data", []) if x.get("id") and not str(x.get("id")).startswith("whisper")})


def _fetch_gemini_models(key: str) -> list[str]:
    req = request.Request("https://generativelanguage.googleapis.com/v1beta/models", headers={"x-goog-api-key": key})
    with request.urlopen(req, timeout=15) as response:
        data = json.loads(response.read().decode())
    result = []
    for item in data.get("models", []):
        model_id = str(item.get("name", "")).removeprefix("models/")
        if model_id.startswith("gemini-") and "generateContent" in (item.get("supportedGenerationMethods", []) or []):
            result.append(model_id)
    return sorted(set(result))


def install_ai_handlers(dp: Dispatcher) -> None:
    if getattr(dp, "_xfi_ai_handlers_installed", False):
        return
    dp._xfi_ai_handlers_installed = True

    @dp.message(F.text == "🟢 Gemini")
    async def select_gemini(m, state):
        if not _admin(m): return
        cfg = load(); cfg["provider"] = "gemini"; save(cfg); await state.clear()
        await m.answer("🟢 Активный AI: Gemini", reply_markup=_ai_menu())

    @dp.message(F.text == "🔵 Groq")
    async def select_groq(m, state):
        if not _admin(m): return
        cfg = load(); cfg["provider"] = "groq"; save(cfg); await state.clear()
        await m.answer("🔵 Активный AI: Groq", reply_markup=_ai_menu())

    @dp.message(F.text == "🔀 Выбрать AI")
    async def choose_ai(m, state):
        if _admin(m):
            cfg = load(); await m.answer(f"Текущий провайдер: {cfg.get('provider', 'gemini').upper()}", reply_markup=_ai_menu())

    @dp.message(F.text == "🔑 Ключ Gemini")
    async def gemini_key_prompt(m, state):
        if _admin(m):
            await state.set_state(AISetupStates.gemini_key)
            await m.answer("Введите API-ключ Gemini:", reply_markup=_kb([["❌ Отмена"], ["⬅️ AI"]]))

    @dp.message(AISetupStates.gemini_key)
    async def gemini_key_save(m, state):
        if not _admin(m): return
        if m.text in {"❌ Отмена", "⬅️ AI"}:
            await state.clear(); await m.answer("Отменено.", reply_markup=_ai_menu()); return
        key = (m.text or "").strip()
        if len(key) < 10:
            await m.answer("❌ Ключ слишком короткий."); return
        cfg = load(); cfg["gemini_key"] = key; cfg["provider"] = "gemini"; save(cfg); await state.clear()
        await m.answer(f"✅ Ключ Gemini сохранён: {_mask(key)}", reply_markup=_ai_menu())

    @dp.message(F.text == "🔑 Ключ Groq")
    async def groq_key_prompt(m, state):
        if _admin(m):
            await state.set_state(AISetupStates.groq_key)
            await m.answer("Введите API-ключ Groq:", reply_markup=_kb([["❌ Отмена"], ["⬅️ AI"]]))

    @dp.message(AISetupStates.groq_key)
    async def groq_key_save(m, state):
        if not _admin(m): return
        if m.text in {"❌ Отмена", "⬅️ AI"}:
            await state.clear(); await m.answer("Отменено.", reply_markup=_ai_menu()); return
        key = (m.text or "").strip()
        if len(key) < 10:
            await m.answer("❌ Ключ слишком короткий."); return
        cfg = load(); cfg["groq_key"] = key; cfg["provider"] = "groq"; save(cfg); await state.clear()
        await m.answer(f"✅ Ключ Groq сохранён: {_mask(key)}", reply_markup=_ai_menu())

    @dp.message(F.text == "🧠 Модель Gemini")
    async def gemini_model_menu(m):
        if _admin(m):
            cfg = load(); await m.answer(f"Модель: {cfg.get('gemini_model', '')}", reply_markup=_model_menu("Gemini", ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-3.1-pro-preview"]))

    @dp.message(F.text == "🧠 Модель Groq")
    async def groq_model_menu(m):
        if _admin(m):
            cfg = load(); await m.answer(f"Модель: {cfg.get('groq_model', '')}", reply_markup=_model_menu("Groq", ["openai/gpt-oss-20b", "openai/gpt-oss-120b", "llama-3.3-70b-versatile", "llama-3.1-8b-instant"]))

    @dp.message(F.text == "📋 Модели Gemini")
    async def gemini_models(m):
        if not _admin(m): return
        key = load().get("gemini_key", "")
        if not key:
            await m.answer("❌ Сначала сохраните ключ Gemini.", reply_markup=_ai_menu()); return
        try:
            models = await asyncio.to_thread(_fetch_gemini_models, key)
            await m.answer("📋 Gemini API:\n\n" + "\n".join(models[:40]), reply_markup=_model_menu("Gemini", models[:20] or ["gemini-2.5-flash"]))
        except Exception as exc:
            await m.answer(f"❌ Gemini API: {type(exc).__name__}: {exc}", reply_markup=_ai_menu())

    @dp.message(F.text == "📋 Модели Groq")
    async def groq_models(m):
        if not _admin(m): return
        key = load().get("groq_key", "")
        if not key:
            await m.answer("❌ Сначала сохраните ключ Groq.", reply_markup=_ai_menu()); return
        try:
            models = await asyncio.to_thread(_fetch_groq_models, key)
            await m.answer("📋 Groq API:\n\n" + "\n".join(models[:40]), reply_markup=_model_menu("Groq", models[:20] or ["openai/gpt-oss-20b"]))
        except Exception as exc:
            await m.answer(f"❌ Groq API: {type(exc).__name__}: {exc}", reply_markup=_ai_menu())

    @dp.message(F.text == "🔄 Получить модели Gemini API")
    async def refresh_gemini(m): await gemini_models(m)

    @dp.message(F.text == "🔄 Получить модели Groq API")
    async def refresh_groq(m): await groq_models(m)

    @dp.message(F.text.startswith("🧠 gemini-"))
    async def choose_gemini_model(m):
        if _admin(m):
            model = (m.text or "").removeprefix("🧠 ").strip(); cfg = load(); cfg["gemini_model"] = model; save(cfg)
            await m.answer(f"✅ Модель Gemini: {model}", reply_markup=_ai_menu())

    @dp.message(F.text.startswith("🧠 openai/"))
    async def choose_groq_openai(m):
        if _admin(m):
            model = (m.text or "").removeprefix("🧠 ").strip(); cfg = load(); cfg["groq_model"] = model; save(cfg)
            await m.answer(f"✅ Модель Groq: {model}", reply_markup=_ai_menu())

    @dp.message(F.text.startswith("🧠 llama-"))
    async def choose_groq_llama(m):
        if _admin(m):
            model = (m.text or "").removeprefix("🧠 ").strip(); cfg = load(); cfg["groq_model"] = model; save(cfg)
            await m.answer(f"✅ Модель Groq: {model}", reply_markup=_ai_menu())

    @dp.message(F.text.startswith("🧠 groq/"))
    async def choose_groq_compound(m):
        if _admin(m):
            model = (m.text or "").removeprefix("🧠 ").strip(); cfg = load(); cfg["groq_model"] = model; save(cfg)
            await m.answer(f"✅ Модель Groq: {model}", reply_markup=_ai_menu())

    @dp.message(F.text == "✏️ Своя модель Gemini")
    async def custom_gemini_prompt(m, state):
        if _admin(m):
            await state.set_state(AISetupStates.gemini_model); await m.answer("Введите ID модели Gemini:", reply_markup=_kb([["❌ Отмена"], ["⬅️ AI"]]))

    @dp.message(AISetupStates.gemini_model)
    async def custom_gemini_save(m, state):
        if not _admin(m): return
        if m.text in {"❌ Отмена", "⬅️ AI"}:
            await state.clear(); await m.answer("Отменено.", reply_markup=_ai_menu()); return
        model = (m.text or "").strip(); cfg = load(); cfg["gemini_model"] = model; save(cfg); await state.clear()
        await m.answer(f"✅ Модель Gemini: {model}", reply_markup=_ai_menu())

    @dp.message(F.text == "✏️ Своя модель Groq")
    async def custom_groq_prompt(m, state):
        if _admin(m):
            await state.set_state(AISetupStates.groq_model); await m.answer("Введите ID модели Groq:", reply_markup=_kb([["❌ Отмена"], ["⬅️ AI"]]))

    @dp.message(AISetupStates.groq_model)
    async def custom_groq_save(m, state):
        if not _admin(m): return
        if m.text in {"❌ Отмена", "⬅️ AI"}:
            await state.clear(); await m.answer("Отменено.", reply_markup=_ai_menu()); return
        model = (m.text or "").strip(); cfg = load(); cfg["groq_model"] = model; save(cfg); await state.clear()
        await m.answer(f"✅ Модель Groq: {model}", reply_markup=_ai_menu())

    @dp.message(F.text == "🧪 Проверить AI")
    async def test_ai(m):
        if not _admin(m): return
        analyzer = AIAnalyzer()
        if not analyzer.enabled():
            await m.answer("❌ AI не настроен. Добавьте API-ключ Gemini, Groq или OpenRouter.", reply_markup=_ai_menu()); return
        result = await asyncio.to_thread(run_health_check)
        failed = [x for x in result["results"] if not x["ok"]]
        lines = ["🧪 AI health-check", "", f"Проверено: {len(result['results'])}", f"Успешно: {len(result['results']) - len(failed)}", f"Ошибок: {len(failed)}", f"Автовыбор: {result.get('recommended_provider') or 'нет'}", "", dashboard_text()]
        await m.answer("\n".join(lines)[:3900], reply_markup=_ai_menu())

    @dp.message(F.text == "📊 Диагностика AI")
    async def ai_diagnostics(m):
        if not _admin(m): return
        result = await asyncio.to_thread(run_health_check)
        lines = ["📊 Диагностика AI", "", f"Автоматически выбран: {result.get('recommended_provider') or 'нет'}", "Провайдеры:"]
        for item in result["results"]:
            state = "✅ OK" if item["ok"] else "❌ FAIL"
            detail = "" if item["ok"] else f" | {item['error'][:180]}"
            lines.append(f"{state} {item['provider']} / {item['model']} — {item['latency_ms']} ms{detail}")
        await m.answer("\n".join(lines)[:3900], reply_markup=_ai_menu())

    @dp.message(F.text == "ℹ️ Статус AI")
    async def ai_status(m):
        if not _admin(m): return
        cfg = load(); analyzer = AIAnalyzer()
        await m.answer("ℹ️ Статус AI\n\n" + f"Провайдер: {cfg.get('provider', 'gemini')}\nАвтовыбор: {cfg.get('ai_auto_selected_provider', 'нет')}\nGemini key: {_mask(cfg.get('gemini_key', ''))}\nGemini model: {cfg.get('gemini_model', '')}\nGroq key: {_mask(cfg.get('groq_key', ''))}\nGroq model: {cfg.get('groq_model', '')}\nГотов: {'ДА' if analyzer.enabled() else 'НЕТ'}\nОшибка: {analyzer.last_error or 'нет'}", reply_markup=_ai_menu())

    @dp.message(F.text == "⬅️ AI")
    async def back_ai(m, state):
        if _admin(m):
            await state.clear(); await m.answer("🤖 Центр AI", reply_markup=_ai_menu())
