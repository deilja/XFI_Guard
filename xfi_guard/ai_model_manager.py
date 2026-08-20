"""API-driven AI model discovery and selection for XFI Guard."""
from __future__ import annotations

import asyncio
import json
import os
from urllib import error, request

from aiogram import F, Dispatcher
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from .ai_store import load, save

PROVIDERS = ("gemini", "groq", "openrouter")


def _kb(rows):
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=x) for x in row] for row in rows], resize_keyboard=True, is_persistent=True)


def _admin(message) -> bool:
    ids = {int(v) for v in os.getenv("XFI_GUARD_ADMIN_IDS", "").split(",") if v.strip().isdigit()}
    return bool(message.from_user and message.from_user.id in ids)


def _request_json(url: str, headers: dict, timeout: float = 15) -> dict:
    req = request.Request(url, headers=headers, method="GET")
    with request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _fetch(provider: str, key: str) -> list[dict]:
    if not key:
        raise RuntimeError("API-ключ не настроен")
    if provider == "gemini":
        data = _request_json("https://generativelanguage.googleapis.com/v1beta/models", {"x-goog-api-key": key})
        return sorted(({"id": str(x.get("name", "")).removeprefix("models/"), "free": True} for x in data.get("models", []) if "generateContent" in (x.get("supportedGenerationMethods", []) or []) and x.get("name")), key=lambda x: x["id"])
    if provider == "groq":
        data = _request_json("https://api.groq.com/openai/v1/models", {"Authorization": f"Bearer {key}", "Accept": "application/json", "User-Agent": "XFI-Guard/1.4"})
        return sorted(({"id": str(x.get("id")), "free": True} for x in data.get("data", []) if x.get("id")), key=lambda x: x["id"])
    if provider == "openrouter":
        data = _request_json("https://openrouter.ai/api/v1/models", {"Authorization": f"Bearer {key}", "HTTP-Referer": "https://github.com/deilja/XFI_Guard", "X-Title": "XFI Guard"})
        result = []
        for item in data.get("data", []):
            model_id = str(item.get("id", "")); pricing = item.get("pricing") or {}
            prompt = str(pricing.get("prompt", "")); completion = str(pricing.get("completion", ""))
            free = prompt in {"0", "0.0", "0.000000", ""} and completion in {"0", "0.0", "0.000000", ""}
            if model_id and free:
                result.append({"id": model_id, "free": True})
        return sorted(result, key=lambda x: x["id"])
    raise ValueError(f"Неизвестный провайдер: {provider}")


def _key(cfg: dict, provider: str) -> str:
    return cfg.get(f"{provider}_key") or os.getenv(f"{provider.upper()}_API_KEY", "")


def _current(cfg: dict, provider: str) -> str:
    return str(cfg.get(f"{provider}_model", ""))


def _save_model(provider: str, model: str) -> None:
    cfg = load(); cfg[f"{provider}_model"] = model
    if provider == "openrouter": cfg["openrouter_models"] = (model,)
    save(cfg)


def install_ai_model_manager(dp: Dispatcher) -> None:
    if getattr(dp, "_xfi_ai_model_manager_installed", False): return
    dp._xfi_ai_model_manager_installed = True

    @dp.message(F.text == "🧩 API модели")
    async def api_models_menu(message):
        if not _admin(message): return
        cfg = load()
        await message.answer(
            "🧩 Выбор бесплатных моделей через API\n\n"
            f"Gemini: {cfg.get('gemini_model', '-')}\n"
            f"Groq: {cfg.get('groq_model', '-')}\n"
            f"OpenRouter: {cfg.get('openrouter_model', 'openrouter/free')}\n\n"
            "Выберите провайдера:",
            reply_markup=_kb([["📡 Gemini API", "📡 Groq API"], ["📡 OpenRouter API"], ["🆓 OpenRouter Free"], ["⬅️ AI"]]),
        )

    async def show_models(message, provider: str):
        if not _admin(message): return
        cfg = load()
        try:
            models = await asyncio.to_thread(_fetch, provider, _key(cfg, provider))
            if not models:
                raise RuntimeError("API не вернуло бесплатных моделей")
            rows = [[f"Выбрать {provider}: {item['id']}"] for item in models[:40]]
            rows += [["🧩 API модели"], ["⬅️ AI"]]
            lines = [f"🆓 {item['id']}" + (" ✅" if item['id'] == _current(cfg, provider) else "") for item in models[:40]]
            await message.answer(f"📡 {provider.upper()} API\n\n" + "\n".join(lines) + "\n\nНажмите модель для выбора.", reply_markup=_kb(rows))
        except error.HTTPError as exc:
            body = exc.read().decode(errors="replace")[:500]
            await message.answer(f"❌ {provider.upper()} API: HTTP {exc.code}\n{body}", reply_markup=_kb([["🧩 API модели"], ["⬅️ AI"]]))
        except Exception as exc:
            await message.answer(f"❌ {provider.upper()} API: {type(exc).__name__}: {exc}", reply_markup=_kb([["🧩 API модели"], ["⬅️ AI"]]))

    for label, provider in (("📡 Gemini API", "gemini"), ("📡 Groq API", "groq"), ("📡 OpenRouter API", "openrouter")):
        @dp.message(F.text == label)
        async def provider_api(message, _provider=provider): await show_models(message, _provider)

    @dp.message(F.text == "🆓 OpenRouter Free")
    async def openrouter_free(message): await show_models(message, "openrouter")

    @dp.message(F.text.startswith("Выбрать "))
    async def select_model(message):
        if not _admin(message): return
        text = message.text or ""
        if ": " not in text: return
        provider, model = text[len("Выбрать "):].split(": ", 1)
        provider = provider.lower(); model = model.strip()
        if provider not in PROVIDERS or not model: return
        cfg = load()
        try:
            models = await asyncio.to_thread(_fetch, provider, _key(cfg, provider))
            if not any(x["id"] == model for x in models):
                await message.answer("❌ Модель не является бесплатной или больше недоступна через API.", reply_markup=_kb([["🧩 API модели"], ["⬅️ AI"]])); return
            _save_model(provider, model)
            await message.answer(f"✅ {provider.upper()}\n\nМодель: {model}\nТип: 🆓\n\nБесплатная модель проверена через API и сохранена.", reply_markup=_kb([["🧩 API модели"], ["⬅️ AI"]]))
        except Exception as exc:
            await message.answer(f"❌ Не удалось проверить модель: {type(exc).__name__}: {exc}", reply_markup=_kb([["🧩 API модели"], ["⬅️ AI"]]))
