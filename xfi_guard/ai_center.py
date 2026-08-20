"""AI Center: health, synchronization and consensus diagnostics for XFI Guard."""
from __future__ import annotations

import asyncio
import os
from aiogram import Dispatcher, F
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup
from .ai import AIAnalyzer, PROVIDERS
from .ai_health import run_health_check, snapshot
from .ai_store import load, save


def _admin(message) -> bool:
    ids={int(v) for v in os.getenv("XFI_GUARD_ADMIN_IDS","").split(",") if v.strip().isdigit()}
    return bool(message.from_user and message.from_user.id in ids)

def _kb(rows):
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=x) for x in row] for row in rows],resize_keyboard=True,is_persistent=True)

def ai_center_menu():
    return _kb([["🩺 Здоровье AI","🧪 Проверить все AI"],["🔑 API ключи","🧩 API модели"],["📊 Консенсус AI","🔄 Синхронизация AI"],["🧹 Сброс здоровья AI"],["⬅️ Главное меню"]])

def build_health_report(data:dict)->str:
    lines=["🩺 Здоровье AI",""]
    for item in data.get("results") or []:
        mark="🟢" if item.get("ok") else "🔴"
        err=f" — {item.get('error')}" if not item.get("ok") and item.get("error") else ""
        lines.append(f"{mark} {item.get('provider')}/{item.get('model')}: {item.get('latency_ms',0)} ms{err}")
    lines += ["",f"Рабочих AI: {sum(bool(x.get('ok')) for x in data.get('results') or [])}/{len(PROVIDERS)}"]
    return "\n".join(lines)[:3900]

def consensus_report(status:dict)->str:
    providers=", ".join(status.get("available_providers") or []) or "нет"; weights=status.get("ai_weights") or {}; health=snapshot(); lines=["📊 Консенсус AI","",f"Активный провайдер: {status.get('selected_provider','unknown')}",f"Настроены: {', '.join(status.get('configured_providers') or []) or 'нет'}",f"Участвуют сейчас: {providers}",f"Минимальный консенсус: {status.get('min_consensus',0.6):.0%}","","Вес:"]
    for provider in PROVIDERS: lines.append(f"• {provider}: {weights.get(provider,1.0)}")
    if health:
        lines += ["","Последние проверки:"]
        for key,value in list(health.items())[-8:]: lines.append(f"• {key}: {value.get('success_rate',0):.0%}, ошибок {value.get('errors',0)}")
    return "\n".join(lines)[:3900]

def install_ai_center_handlers(dp:Dispatcher)->None:
    if getattr(dp,"_xfi_ai_center_handlers_installed",False): return
    dp._xfi_ai_center_handlers_installed=True

    @dp.message(F.text == "🩺 Здоровье AI")
    async def health(m):
        if not _admin(m): return
        await m.answer("⏳ Проверяю Gemini, Groq и OpenRouter...")
        try: await m.answer(build_health_report(await asyncio.to_thread(run_health_check)),reply_markup=ai_center_menu())
        except Exception as exc: await m.answer(f"❌ AI health: {type(exc).__name__}: {exc}",reply_markup=ai_center_menu())

    @dp.message(F.text == "🧪 Проверить все AI")
    async def check_all(m):
        if not _admin(m): return
        await m.answer("⏳ Реальная проверка API трёх бесплатных AI...")
        try: await m.answer(build_health_report(await asyncio.to_thread(run_health_check)),reply_markup=ai_center_menu())
        except Exception as exc: await m.answer(f"❌ Проверка AI: {type(exc).__name__}: {exc}",reply_markup=ai_center_menu())

    @dp.message(F.text == "🔄 Синхронизация AI")
    async def sync(m):
        if not _admin(m): return
        try:
            analyzer=AIAnalyzer(); analyzer.sync(); status=analyzer.status(); cfg=load(); cfg.update({"provider":status["selected_provider"],"openrouter_model":status["openrouter_model"],"openrouter_models":tuple(status["openrouter_models"]) }); save(cfg)
            await m.answer("🔄 AI синхронизирован\n\n"+f"Доступны по ключу: {', '.join(status['available_providers']) or 'нет'}\n"+f"Gemini: {status['gemini_model']}\nGroq: {status['groq_model']}\nOpenRouter: {status['openrouter_model']}",reply_markup=ai_center_menu())
        except Exception as exc: await m.answer(f"❌ Синхронизация AI: {type(exc).__name__}: {exc}",reply_markup=ai_center_menu())

    @dp.message(F.text == "📊 Консенсус AI")
    async def consensus(m):
        if _admin(m): await m.answer(consensus_report(AIAnalyzer().status()),reply_markup=ai_center_menu())

    @dp.message(F.text == "🧹 Сброс здоровья AI")
    async def reset(m):
        if not _admin(m): return
        AIAnalyzer().reset_health(); await m.answer("🧹 Локальные cooldown/failure-состояния AI сброшены.",reply_markup=ai_center_menu())
