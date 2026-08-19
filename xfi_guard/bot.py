"""Telegram admin bot for XFI Guard. Интерфейс бота на русском языке."""
from __future__ import annotations
import asyncio, ipaddress, json, os, subprocess
from urllib import request
from .ai import AIAnalyzer
from .ai_store import load as load_ai, save as save_ai
from .checks import collect_basic_checks
from .events import parse_file
from .attack_surface import collect_attack_surface
from .security import collect_security_checks
from .security_center import ai_report, summarize
from .security_brain import analyze as brain_analyze
from .security_brain_ui import format_brain_report
from .vpn import collect_vpn_checks
from .firewall import block_ip, unblock_ip, list_blocked_ips, validate_public_ip
from .auto_defense import confirm_block
from .gemini import normalize_model
from .alert_callbacks import register_alert_callbacks
from .rate_limit import RateLimitMiddleware
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

TOKEN = os.getenv("XFI_GUARD_BOT_TOKEN")
ADMIN_IDS = {int(v) for v in os.getenv("XFI_GUARD_ADMIN_IDS", "").split(",") if v.strip().isdigit()}
WEBHOOK_DOMAIN = os.getenv("XFI_GUARD_WEBHOOK_DOMAIN", "").strip().rstrip("/")
WEBHOOK_PATH = os.getenv("XFI_GUARD_WEBHOOK_PATH", "/xfi-guard/webhook").strip() or "/xfi-guard/webhook"
WEBHOOK_SECRET = os.getenv("XFI_GUARD_WEBHOOK_SECRET", "").strip()
WEBHOOK_HOST = os.getenv("XFI_GUARD_WEBHOOK_HOST", "127.0.0.1")
WEBHOOK_PORT = int(os.getenv("XFI_GUARD_WEBHOOK_PORT", "8080"))

GROQ_MODELS = [("🧠 GPT-OSS 120B", "openai/gpt-oss-120b"), ("🧠 GPT-OSS 20B", "openai/gpt-oss-20b"), ("🦙 Llama 3.3 70B", "llama-3.3-70b-versatile"), ("⚡ Llama 3.1 8B", "llama-3.1-8b-instant"), ("🌐 Groq Compound", "groq/compound"), ("🚀 Groq Compound Mini", "groq/compound-mini")]
GEMINI_MODELS = [("🧠 Gemini 3.1 Pro", "gemini-3.1-pro-preview"), ("⚡ Gemini 3.6 Flash", "gemini-3.6-flash"), ("⚡ Gemini 3.5 Flash", "gemini-3.5-flash"), ("🚀 Gemini 3.5 Flash Lite", "gemini-3.5-flash-lite"), ("⚡ Gemini 3.1 Flash Lite", "gemini-3.1-flash-lite"), ("🌐 Gemini 3 Flash Preview", "gemini-3-flash-preview"), ("🧠 Gemini 2.5 Pro", "gemini-2.5-pro"), ("⚡ Gemini 2.5 Flash", "gemini-2.5-flash")]

class SetupStates(StatesGroup):
    provider = State(); gemini_key = State(); groq_key = State(); openrouter_key = State(); gemini_model = State(); groq_model = State(); openrouter_model = State(); block_ip = State(); confirm_block = State(); unblock_ip = State()

def admin(m): return bool(m.from_user and m.from_user.id in ADMIN_IDS)
def mask(k): return k[:4] + "…" + k[-4:] if len(k) >= 8 else ("настроен" if k else "не настроен")
def kb(rows): return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=x) for x in row] for row in rows], resize_keyboard=True, is_persistent=True)
def main_kb(): return kb([["📊 Статус", "🔐 Безопасность"], ["🛡 Fail2Ban", "🔥 UFW"], ["🌐 VPN/Xray", "📋 События"], ["🛡 Картина атак", "🤖 AI"], ["🧠 Security Brain", "🧠 Центр AI"], ["🚫 Блокировка IP", "🔄 Проверить сейчас"], ["🔄 Обновить XFI Guard"], ["❓ Помощь"]])
def ai_kb(): return kb([["🟢 Gemini", "🔵 Groq", "🟣 OpenRouter"], ["🔀 Все AI вместе"], ["🔑 Ключ Gemini", "🔑 Ключ Groq"], ["🔑 Ключ OpenRouter"], ["🧠 Модель Gemini", "🧠 Модель Groq"], ["🧠 Модель OpenRouter"], ["🧪 Проверить AI", "ℹ️ Статус AI"], ["⬅️ Главное меню"]])
def center_kb(): return kb([["📊 Анализ за 24 часа"], ["🚨 Топ атакующих IP"], ["🤖 AI-анализ сводки"], ["🤖 Рекомендации блокировки"], ["🔄 Обновить"], ["⬅️ Главное меню"]])
def block_kb(): return kb([["🤖 Рекомендации AI"], ["📋 Выбрать IP из событий"], ["✏️ Ввести IP вручную"], ["📋 Заблокированные IP", "🔓 Разблокировать IP"], ["⬅️ Главное меню"]])
def results(r): return "\n".join(f"{getattr(x, 'status', 'unknown').upper()}: {x.name} — {x.message}" for x in r)[:3800] or "Нет данных."
def events():
    from .config import load_config
    c = load_config(); return parse_file(c.ssh_log, "ssh") + parse_file(c.fail2ban_log, "fail2ban")
def active_events():
    blocked = {str(ip).strip() for ip in list_blocked_ips()}; return [e for e in events() if not getattr(e, "ip", None) or str(e.ip).strip() not in blocked]
def event_dicts(): return [{"timestamp": getattr(e, "timestamp", ""), "severity": getattr(e, "severity", "unknown"), "event_type": getattr(e, "event_type", "unknown"), "ip": getattr(e, "ip", None), "user": getattr(e, "user", None), "message": getattr(e, "message", "")} for e in active_events()]
def attack_surface_text():
    data = collect_attack_surface(); blocked = {str(i).strip() for i in list_blocked_ips()}; items = [x for x in data.get("ips", []) if str(x.get("ip", "")) not in blocked]
    lines = ["🛡 Полная картина атак за текущий период", "", f"Fail2Ban: {data.get('fail2ban_count', 0)}", f"UFW DENY/REJECT: {data.get('ufw_count', 0)}", f"SSH неудачных входов: {data.get('ssh_count', 0)}", f"Уникальных активных IP: {len(items)}", ""]
    for x in items[:15]: lines.append(f"• {x['ip']} — {x['risk']} ({x['risk_score']}/100) | источники: {', '.join(x['sources'])} | событий: {x['events']}")
    return "\n".join(lines)[:3900]
def fetch_groq_models(key):
    req = request.Request("https://api.groq.com/openai/v1/models", headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with request.urlopen(req, timeout=15) as response: data = json.loads(response.read().decode())
    return sorted({str(x.get("id")) for x in data.get("data", []) if x.get("id") and not str(x.get("id")).startswith("whisper")})
def fetch_gemini_models(key):
    req = request.Request("https://generativelanguage.googleapis.com/v1beta/models", headers={"x-goog-api-key": key, "Content-Type": "application/json"})
    with request.urlopen(req, timeout=15) as response: data = json.loads(response.read().decode())
    return sorted({str(x.get("name", "")).removeprefix("models/") for x in data.get("models", []) if str(x.get("name", "")).startswith("models/gemini-") and "generateContent" in (x.get("supportedGenerationMethods", []) or [])})
def groq_model_kb(models, current):
    names = {mid: label for label, mid in GROQ_MODELS}; rows = [["⬅️ AI"]]
    for model in models: rows.append([("✅ " if model == current else "") + names.get(model, model)])
    return kb(rows)

def build_dispatcher():
    dp = Dispatcher(storage=MemoryStorage())
    rate_limit = RateLimitMiddleware(rate=2, period=1.0)
    dp.message.middleware(rate_limit)
    dp.callback_query.middleware(rate_limit)
    register_alert_callbacks(dp, ADMIN_IDS)
    return dp

async def main():
    if not TOKEN:
        raise RuntimeError("XFI_GUARD_BOT_TOKEN не задан")
    dp = build_dispatcher()
    bot = Bot(TOKEN)
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
