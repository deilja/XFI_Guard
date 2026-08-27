"""AI Center: health, synchronization and consensus diagnostics for XFI Guard."""
from __future__ import annotations
import asyncio
from aiogram import Dispatcher, F
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup
from .admin_auth import authorized
from .ai import AIAnalyzer, PROVIDERS
from .ai_health import run_health_check, snapshot
from .ai_store import load, save

def _admin(message): return authorized(message)
def _kb(rows): return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=x) for x in row] for row in rows],resize_keyboard=True,is_persistent=True)
def ai_center_menu(): return _kb([["🩺 Здоровье AI","🧪 Проверить все AI"],["🔑 API ключи","🧩 API модели"],["📊 Консенсус AI","🔄 Синхронизация AI"],["🧹 Сброс здоровья AI"],["⬅️ Главное меню"]])
def build_health_report(data):
    results=data.get("results") or []
    if not results: return "🩺 Здоровье AI\n\nНет доступных AI-провайдеров\n\nРабочих AI: 0/0"
    lines=["🩺 Здоровье AI",""]
    for item in results:
        mark="🟢" if item.get("ok") else "🔴"; err=f" — {item.get('error')}" if not item.get("ok") and item.get("error") else ""
        lines.append(f"{mark} {item.get('provider')}/{item.get('model')}: {item.get('latency_ms',0)} ms{err}")
    total=len(results); working=sum(bool(x.get("ok")) for x in results); lines += ["",f"Рабочих AI: {working}/{total}"]; return "\n".join(lines)[:3900]
def consensus_report(status):
    providers=", ".join(status.get("available_providers") or []) or "нет"; weights=status.get("ai_weights") or {}; health=snapshot(); lines=["📊 Консенсус AI","",f"Активный провайдер: {status.get('selected_provider','unknown')}",f"Настроены: {', '.join(status.get('configured_providers') or []) or 'нет'}",f"Участвуют сейчас: {providers}",f"Минимальный консенсус: {status.get('min_consensus',0.6):.0%}","","Вес:"]
    for provider in PROVIDERS: lines.append(f"• {provider}: {weights.get(provider,1.0)}")
    if health:
        lines += ["","Последние проверки:"]; lines += [f"• {k}: {v.get('success_rate',0):.0%}, ошибок {v.get('errors',0)}" for k,v in list(health.items())[-8:]]
    return "\n".join(lines)[:3900]
def install_ai_center_handlers(dp:Dispatcher)->None:
    if getattr(dp,"_xfi_ai_center_handlers_installed",False): return
    dp._xfi_ai_center_handlers_installed=True
    @dp.message(F.text=="🩺 Здоровье AI")
    async def health(m):
        if not _admin(m): return
        await m.answer("⏳ Проверяю Gemini, Groq, OpenRouter и RouterAI...")
        try: await m.answer(build_health_report(await asyncio.to_thread(run_health_check)),reply_markup=ai_center_menu())
        except Exception: await m.answer("❌ Проверка AI завершилась ошибкой. Подробности записаны в журнал.",reply_markup=ai_center_menu())
    @dp.message(F.text=="🧪 Проверить все AI")
    async def check_all(m):
        if not _admin(m): return
        await m.answer("⏳ Реальная проверка API Gemini, Groq, OpenRouter и RouterAI...")
        try: await m.answer(build_health_report(await asyncio.to_thread(run_health_check)),reply_markup=ai_center_menu())
        except Exception: await m.answer("❌ Проверка AI завершилась ошибкой. Подробности записаны в журнал.",reply_markup=ai_center_menu())
    @dp.message(F.text=="🔄 Синхронизация AI")
    async def sync(m):
        if not _admin(m): return
        try:
            analyzer=AIAnalyzer(); analyzer.sync(); status=analyzer.status(); cfg=load(); cfg.update({"provider":status["selected_provider"],"openrouter_model":status["openrouter_model"],"openrouter_models":tuple(status["openrouter_models"]),"routerai_model":status.get("routerai_model",""),"routerai_models":tuple(status.get("routerai_models") or [])}); save(cfg)
            await m.answer("🔄 AI синхронизирован\n\n"+f"Доступны по ключу: {', '.join(status['available_providers']) or 'нет'}\n"+f"Gemini: {status['gemini_model']}\n"+f"Groq: {status['groq_model']}\n"+f"OpenRouter: {status['openrouter_model']}\n"+f"RouterAI: {status.get('routerai_model') or 'не выбран'}\n"+f"RouterAI моделей: {len(status.get('routerai_models') or [])}\n"+f"Платный fallback: {'включён' if status.get('routerai_allow_paid') else 'выключен'}",reply_markup=ai_center_menu())
        except Exception: await m.answer("❌ Синхронизация AI завершилась ошибкой. Подробности записаны в журнал.",reply_markup=ai_center_menu())
    @dp.message(F.text=="📊 Консенсус AI")
    async def consensus(m):
        if _admin(m): await m.answer(consensus_report(AIAnalyzer().status()),reply_markup=ai_center_menu())
    @dp.message(F.text=="🧹 Сброс здоровья AI")
    async def reset(m):
        if not _admin(m): return
        AIAnalyzer().reset_health(); await m.answer("🧹 Локальные cooldown/failure-состояния AI сброшены.",reply_markup=ai_center_menu())
