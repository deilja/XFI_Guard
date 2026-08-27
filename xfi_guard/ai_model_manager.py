"""API-driven AI model discovery and selection for XFI Guard."""
from __future__ import annotations

import asyncio
import json
import os
from urllib import error, request

from aiogram import F, Dispatcher
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from .ai_store import load, save
from .routerai import RouterAIAdapter

PROVIDERS = ("gemini", "groq", "openrouter", "routerai")


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
    if not key: raise RuntimeError("API-ключ не настроен")
    if provider == "gemini":
        data = _request_json("https://generativelanguage.googleapis.com/v1beta/models", {"x-goog-api-key": key})
        return sorted(({"id": str(x.get("name", "")).removeprefix("models/"), "free": True} for x in data.get("models", []) if "generateContent" in (x.get("supportedGenerationMethods", []) or []) and x.get("name")), key=lambda x: x["id"])
    if provider == "groq":
        data = _request_json("https://api.groq.com/openai/v1/models", {"Authorization": f"Bearer {key}", "Accept": "application/json", "User-Agent": "XFI-Guard/1.9"})
        return sorted(({"id": str(x.get("id")), "free": True} for x in data.get("data", []) if x.get("id")), key=lambda x: x["id"])
    if provider == "openrouter":
        data = _request_json("https://openrouter.ai/api/v1/models", {"Authorization": f"Bearer {key}", "HTTP-Referer": "https://github.com/deilja/XFI_Guard", "X-Title": "XFI Guard"})
        result=[]
        for item in data.get("data", []):
            model_id=str(item.get("id","")); pricing=item.get("pricing") or {}; prompt=str(pricing.get("prompt","")); completion=str(pricing.get("completion",""))
            if model_id and prompt in {"0","0.0","0.000000",""} and completion in {"0","0.0","0.000000",""}: result.append({"id":model_id,"free":True})
        return sorted(result,key=lambda x:x["id"])
    if provider == "routerai":
        adapter=RouterAIAdapter(key,timeout=15); all_models=adapter.models(force=True)
        if not all_models: raise RuntimeError(adapter.last_error or "API не вернуло моделей")
        free=set(adapter.free_models(all_models,force=True)); return [{"id":m,"free":m in free} for m in all_models]
    raise ValueError(f"Неизвестный провайдер: {provider}")


def _key(cfg: dict, provider: str) -> str: return cfg.get(f"{provider}_key") or os.getenv(f"{provider.upper()}_API_KEY", "")
def _current(cfg: dict, provider: str) -> str: return str(cfg.get(f"{provider}_model", ""))


def _save_model(provider: str, model: str, free: bool = True) -> None:
    cfg=load(); cfg[f"{provider}_model"]=model
    if provider == "openrouter": cfg["openrouter_models"]=(model,)
    if provider == "routerai":
        cfg["routerai_models"]=(model,); cfg["routerai_enabled"]=True
        # Selecting a paid model never grants paid inference permission.
        cfg["routerai_allow_paid"] = bool(cfg.get("routerai_allow_paid", False)) if free else False
    save(cfg)


def install_ai_model_manager(dp: Dispatcher) -> None:
    if getattr(dp,"_xfi_ai_model_manager_installed",False): return
    dp._xfi_ai_model_manager_installed=True

    @dp.message(F.text == "🧩 API модели")
    async def api_models_menu(message):
        if not _admin(message): return
        cfg=load(); paid=bool(cfg.get("routerai_allow_paid",False))
        await message.answer("🧩 Выбор моделей через API\n\n" f"Gemini: {cfg.get('gemini_model','-')}\n" f"Groq: {cfg.get('groq_model','-')}\n" f"OpenRouter: {cfg.get('openrouter_model','openrouter/free')}\n" f"RouterAI: {cfg.get('routerai_model','-') or '-'}\n\nRouterAI: бесплатные модели имеют приоритет. Платные модели требуют отдельного явного разрешения. Сейчас paid: {'ON' if paid else 'OFF'}.\n\nВыберите провайдера:", reply_markup=_kb([["📡 Gemini API","📡 Groq API"],["📡 OpenRouter API","📡 RouterAI API"],["🆓 OpenRouter Free"],["⬅️ AI"]]))

    async def show_models(message, provider: str):
        if not _admin(message): return
        cfg=load()
        try:
            models=await asyncio.to_thread(_fetch,provider,_key(cfg,provider))
            if not models: raise RuntimeError("API не вернуло моделей")
            visible=models[:100]; rows=[[f"Выбрать {provider}: {x['id']}"] for x in visible]+[["🧩 API модели"],["⬅️ AI"]]
            lines=[f"{'🆓' if x['free'] else '💳'} {x['id']}"+(" ✅" if x['id']==_current(cfg,provider) else "") for x in visible]
            free_count=sum(1 for x in models if x["free"]); paid_count=len(models)-free_count
            suffix="" if len(visible)==len(models) else f"\n\nПоказано {len(visible)} из {len(models)}."
            await message.answer(f"📡 {provider.upper()} API\n\n"+"\n".join(lines)+f"\n\n🆓 Бесплатных: {free_count}  💳 Платных: {paid_count}"+suffix+"\n\nНажмите модель для выбора.",reply_markup=_kb(rows))
        except error.HTTPError as exc:
            await message.answer(f"❌ {provider.upper()} API: HTTP {exc.code}",reply_markup=_kb([["🧩 API модели"],["⬅️ AI"]]))
        except Exception:
            await message.answer(f"❌ Не удалось получить список моделей {provider.upper()} API.",reply_markup=_kb([["🧩 API модели"],["⬅️ AI"]]))

    for label,provider in (("📡 Gemini API","gemini"),("📡 Groq API","groq"),("📡 OpenRouter API","openrouter"),("📡 RouterAI API","routerai")):
        @dp.message(F.text == label)
        async def provider_api(message,_provider=provider): await show_models(message,_provider)
    @dp.message(F.text == "🆓 OpenRouter Free")
    async def openrouter_free(message):
        if _admin(message): await show_models(message,"openrouter")

    @dp.message(F.text.startswith("Выбрать "))
    async def select_model(message):
        if not _admin(message): return
        text=message.text or ""
        if ": " not in text: return
        provider,model=text[len("Выбрать "):].split(": ",1); provider=provider.lower(); model=model.strip()
        if provider not in PROVIDERS or not model: return
        cfg=load()
        try:
            models=await asyncio.to_thread(_fetch,provider,_key(cfg,provider)); selected=next((x for x in models if x["id"]==model),None)
            if selected is None: await message.answer("❌ Модель больше недоступна через API.",reply_markup=_kb([["🧩 API модели"],["⬅️ AI"]])); return
            if provider=="routerai" and not selected["free"] and not bool(cfg.get("routerai_allow_paid",False)):
                await message.answer("❌ Платная RouterAI-модель запрещена текущей политикой. Сначала явно включите paid inference.",reply_markup=_kb([["🧩 API модели"],["⬅️ AI"]])); return
            _save_model(provider,model,bool(selected["free"])); kind="🆓 Бесплатная" if selected["free"] else "💳 Платная fallback (разрешена политикой)"
            await message.answer(f"✅ {provider.upper()}\n\nМодель: {model}\nТип: {kind}\n\nМодель проверена через API и сохранена.",reply_markup=_kb([["🧩 API модели"],["⬅️ AI"]]))
        except Exception:
            await message.answer("❌ Не удалось проверить или сохранить модель.",reply_markup=_kb([["🧩 API модели"],["⬅️ AI"]]))
