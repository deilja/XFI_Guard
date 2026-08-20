"""AI Telegram UI handlers for XFI Guard."""
from __future__ import annotations

import asyncio
import json
import os
from urllib import error, request

from aiogram import F, Dispatcher
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from .ai_store import load, save
from .ai import AIAnalyzer


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
        ["🧪 Проверить AI", "🧪 Проверить Groq"], ["ℹ️ Статус AI"],
        ["⬅️ Главное меню"],
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


def _groq_diagnostics(key: str, preferred_model: str) -> dict:
    """Проверяет Groq models endpoint и делает минимальный chat-запрос."""
    models_url = "https://api.groq.com/openai/v1/models"
    chat_url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json", "User-Agent": "XFI-Guard/1.2"}
    try:
        req = request.Request(models_url, headers=headers, method="GET")
        with request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read().decode())
        available = sorted({str(x.get("id")) for x in data.get("data", []) if x.get("id")})
    except error.HTTPError as exc:
        body = exc.read().decode(errors="replace")[:500]
        return {"ok": False, "stage": "models", "error": f"HTTP {exc.code}: {body}"}
    except Exception as exc:
        return {"ok": False, "stage": "models", "error": f"{type(exc).__name__}: {exc}"}

    candidates = [preferred_model, "openai/gpt-oss-20b", "llama-3.1-8b-instant", "llama-3.3-70b-versatile"]
    model = next((x for x in candidates if x and x in available), None)
    if not model:
        return {"ok": False, "stage": "model", "error": f"Модель {preferred_model} недоступна. Доступных моделей: {len(available)}", "models": available[:30]}

    body = {
        "model": model,
        "messages": [{"role": "user", "content": "Ответь одним словом: OK"}],
        "temperature": 0,
        "max_tokens": 8,
    }
    try:
        req = request.Request(chat_url, data=json.dumps(body).encode(), headers=headers, method="POST")
        with request.urlopen(req, timeout=20) as response:
            payload = json.loads(response.read().decode())
        answer = ((payload.get("choices") or [{}])[0].get("message") or {}).get("content", "").strip()
        if not answer:
            return {"ok": False, "stage": "chat", "model": model, "error": "Groq вернул пустой ответ"}
        return {"ok": True, "model": model, "answer": answer, "models": available}
    except error.HTTPError as exc:
        body = exc.read().decode(errors="replace")[:700]
        return {"ok": False, "stage": "chat", "model": model, "error": f"HTTP {exc.code}: {body}", "models": available}
    except Exception as exc:
        return {"ok": False, "stage": "chat", "model": model, "error": f"{type(exc).__name__}: {exc}", "models": available}


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
            await m.answer(f"❌ AI не настроен. {analyzer.last_error or 'Добавьте API-ключ.'}", reply_markup=_ai_menu()); return
        result = await asyncio.to_thread(analyzer.analyze, {"event_type": "health_check", "severity": "info", "message": "Проверка AI XFI Guard. Ответь: AI работает."})
        await m.answer(("✅ AI работает\n\n" + result[:3500]) if result else ("❌ AI не вернул ответ.\n\n" + (analyzer.last_error or "Неизвестная ошибка")), reply_markup=_ai_menu())

    @dp.message(F.text == "🧪 Проверить Groq")
    async def test_groq(m):
        if not _admin(m): return
        cfg = load(); key = cfg.get("groq_key") or os.getenv("GROQ_API_KEY", "")
        if not key:
            await m.answer("❌ Groq API-ключ не настроен.", reply_markup=_ai_menu()); return
        await m.answer("🔎 Проверяю Groq API и доступность модели...")
        result = await asyncio.to_thread(_groq_diagnostics, key, cfg.get("groq_model") or "openai/gpt-oss-20b")
        if result.get("ok"):
            await m.answer(f"✅ Groq работает\n\nEndpoint: https://api.groq.com/openai/v1\nМодель: {result['model']}\nОтвет: {result['answer']}\nДоступных моделей: {len(result.get('models', []))}", reply_markup=_ai_menu())
        else:
            details = result.get("error", "Неизвестная ошибка")
            extra = ""
            if result.get("models"):
                extra = "\n\nДоступные модели:\n" + "\n".join(result["models"][:20])
            await m.answer(f"❌ Groq не прошёл проверку\n\nЭтап: {result.get('stage', '-')}\n{details}{extra}"[:3900], reply_markup=_ai_menu())

    @dp.message(F.text == "ℹ️ Статус AI")
    async def ai_status(m):
        if not _admin(m): return
        cfg = load(); analyzer = AIAnalyzer()
        await m.answer("ℹ️ Статус AI\n\n" + f"Провайдер: {cfg.get('provider', 'gemini')}\nGemini key: {_mask(cfg.get('gemini_key', ''))}\nGemini model: {cfg.get('gemini_model', '')}\nGroq key: {_mask(cfg.get('groq_key', ''))}\nGroq model: {cfg.get('groq_model', '')}\nГотов: {'ДА' if analyzer.enabled() else 'НЕТ'}\nОшибка: {analyzer.last_error or 'нет'}", reply_markup=_ai_menu())

    @dp.message(F.text == "⬅️ AI")
    async def back_ai(m, state):
        if _admin(m):
            await state.clear(); await m.answer("🤖 Центр AI", reply_markup=_ai_menu())
