"""Telegram admin bot for XFI Guard. Интерфейс бота на русском языке."""
from __future__ import annotations

import asyncio
import os
import subprocess

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from .ai_ui import install_ai_handlers
from .ai_center import install_ai_center_handlers, ai_center_menu
from .openrouter_ui import install_openrouter_handlers
from .xui_ui import install_xui_handlers
from .alert_callbacks import register_alert_callbacks
from .attack_surface import collect_attack_surface
from .checks import collect_basic_checks
from .defense_ui import install_defense_handlers
from .rate_limit import RateLimitMiddleware
from .security import collect_security_checks
from .vpn import collect_vpn_checks

ADMIN_IDS = {int(v) for v in os.getenv("XFI_GUARD_ADMIN_IDS", "").split(",") if v.strip().isdigit()}


def admin(message) -> bool:
    return bool(message.from_user and message.from_user.id in ADMIN_IDS)


def kb(rows: list[list[str]]) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=x) for x in row] for row in rows], resize_keyboard=True, is_persistent=True)


def main_kb() -> ReplyKeyboardMarkup:
    return kb([["📊 Статус", "🔐 Безопасность"], ["🛡 Fail2Ban", "🔥 UFW"], ["🌐 VPN/Xray", "📋 События"], ["⚙️ 3X-UI", "🤖 AI"], ["🛡 Картина атак", "🧠 Security Brain"], ["🚫 Блокировка IP"], ["🔄 Проверить сейчас"], ["🔄 Обновить XFI Guard", "⚡ Принудительное обновление"], ["❓ Помощь"]])


def results(items) -> str:
    return "\n".join(f"{getattr(x, 'status', 'unknown').upper()}: {getattr(x, 'name', 'check')} — {getattr(x, 'message', '')}" for x in items)[:3800] or "Нет данных."


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    rate_limit = RateLimitMiddleware(rate=2, period=1.0)
    dp.message.middleware(rate_limit)
    dp.callback_query.middleware(rate_limit)
    register_alert_callbacks(dp, ADMIN_IDS)
    install_ai_handlers(dp)
    install_ai_center_handlers(dp)
    install_openrouter_handlers(dp)
    install_xui_handlers(dp)
    install_defense_handlers(dp)

    @dp.message(Command("start"))
    async def start(message, state: FSMContext):
        await state.clear()
        if admin(message):
            await message.answer("🛡 XFI Guard\n\nПанель управления сервером активна.", reply_markup=main_kb())

    @dp.message(Command("status"))
    async def status_command(message):
        if admin(message):
            await message.answer("📊 Статус XFI Guard\n\n" + results(collect_basic_checks() + collect_security_checks() + collect_vpn_checks()), reply_markup=main_kb())

    @dp.message(F.text == "📊 Статус")
    async def status_button(message):
        await status_command(message)

    @dp.message(F.text == "🔐 Безопасность")
    async def security_button(message):
        if admin(message):
            await message.answer("🔐 Безопасность\n\n" + results(collect_security_checks()), reply_markup=main_kb())

    @dp.message(F.text == "🛡 Fail2Ban")
    async def fail2ban_button(message):
        if admin(message):
            checks = [x for x in collect_security_checks() if getattr(x, "name", "") == "fail2ban"]
            await message.answer("🛡 Fail2Ban\n\n" + results(checks), reply_markup=main_kb())

    @dp.message(F.text == "🔥 UFW")
    async def ufw_button(message):
        if admin(message):
            checks = [x for x in collect_security_checks() if getattr(x, "name", "") == "ufw"]
            await message.answer("🔥 UFW\n\n" + results(checks), reply_markup=main_kb())

    @dp.message(F.text == "🌐 VPN/Xray")
    async def vpn_button(message):
        if admin(message):
            await message.answer("🌐 VPN/Xray\n\n" + results(collect_vpn_checks()), reply_markup=main_kb())

    @dp.message(F.text == "📋 События")
    async def events_button(message):
        if not admin(message):
            return
        try:
            p = subprocess.run(["journalctl", "-u", "xfi-guard", "-u", "xfi-guard-bot", "-n", "40", "--no-pager"], text=True, capture_output=True, timeout=8, check=False)
            text = (p.stdout or p.stderr).strip()[-3600:] or "Событий нет."
        except Exception as exc:
            text = f"❌ Не удалось получить события: {type(exc).__name__}: {exc}"
        await message.answer("📋 Последние события\n\n" + text, reply_markup=main_kb())

    @dp.message(F.text == "🛡 Картина атак")
    async def attack_surface_button(message):
        if not admin(message):
            return
        data = collect_attack_surface()
        text = ["🛡 Полная картина атак", "", f"Fail2Ban: {data.get('fail2ban_count', 0)}", f"UFW DENY/REJECT: {data.get('ufw_count', 0)}", f"SSH неудачных входов: {data.get('ssh_count', 0)}", f"Уникальных IP: {len(data.get('ips', []))}", ""]
        for item in data.get("ips", [])[:15]:
            text.append(f"• {item.get('ip', '-')} — {item.get('risk', 'unknown')} ({item.get('risk_score', 0)}/100), событий: {item.get('events', 0)}")
        await message.answer("\n".join(text)[:3900], reply_markup=main_kb())

    @dp.message(F.text == "🧠 Security Brain")
    async def brain_button(message):
        if not admin(message):
            return
        await message.answer("🧠 Security Brain запускается...", reply_markup=main_kb())
        try:
            from .security_brain import analyze
            from .security_brain_ui import format_brain_report
            report = await asyncio.to_thread(analyze, 10)
            await message.answer(format_brain_report(report), reply_markup=main_kb())
        except Exception as exc:
            await message.answer(f"❌ Security Brain: {type(exc).__name__}: {exc}", reply_markup=main_kb())

    @dp.message(F.text == "🔄 Проверить сейчас")
    async def check_button(message):
        await status_command(message)

    @dp.message(F.text == "🔄 Обновить XFI Guard")
    async def update_button(message):
        if not admin(message):
            return
        await message.answer("⏳ Запускаю безопасное обновление XFI Guard...")
        subprocess.Popen(["systemctl", "start", "xfi-guard-update.service"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    @dp.message(F.text == "⚡ Принудительное обновление")
    async def force_update_button(message):
        if not admin(message):
            return
        await message.answer("⚠️ Принудительное обновление XFI Guard\n\nБудет заново установлен текущий origin/main, даже если SHA совпадает.\nПеред заменой создаётся точка отката, после установки выполняется проверка бота.")
        subprocess.Popen(["/opt/xfi-guard/.venv/bin/python", "-m", "xfi_guard.force_update"], cwd="/opt/xfi-guard", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    @dp.message(Command("force_update"))
    async def force_update_command(message):
        await force_update_button(message)

    @dp.message(F.text == "🤖 AI")
    async def ai_button(message):
        if admin(message):
            await message.answer("🤖 Центр AI\n\nВыберите провайдера или действие ниже.", reply_markup=kb([["🟢 Gemini", "🔵 Groq"], ["🟣 OpenRouter", "🔀 Выбрать AI"], ["🔑 Ключ Gemini", "🔑 Ключ Groq"], ["🧠 Модель Gemini", "🧠 Модель Groq"], ["🧪 Проверить AI", "ℹ️ Статус AI"], ["🩺 Здоровье AI", "🔄 Синхронизация AI"], ["📊 Консенсус AI", "🧹 Сброс здоровья AI"], ["⬅️ Главное меню"]]))

    @dp.message(F.text == "🚫 Блокировка IP")
    async def block_button(message):
        if admin(message):
            await message.answer("🚫 Управление защитой IP\n\nAI только рекомендует. Автоматическое удаление клиентов и inbound не выполняется.", reply_markup=main_kb())

    @dp.message(F.text == "❓ Помощь")
    async def help_button(message):
        if admin(message):
            await message.answer("❓ XFI Guard\n\n/start — главное меню\n/status — полный статус\n/force_update — принудительно переустановить origin/main\n/threats — рейтинг угроз\n/defense_history — история защиты\n\nИнтерфейс и ответы бота на русском языке.", reply_markup=main_kb())

    @dp.message(F.text == "⬅️ Главное меню")
    async def back_main(message, state: FSMContext):
        if admin(message):
            await state.clear()
            await message.answer("🏠 Главное меню", reply_markup=main_kb())

    @dp.message()
    async def unknown_message(message):
        if admin(message):
            await message.answer("Команда не распознана. Нажмите /start для открытия панели XFI Guard.", reply_markup=main_kb())

    return dp


async def main() -> None:
    token = os.getenv("XFI_GUARD_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("XFI_GUARD_BOT_TOKEN не задан")
    dp = build_dispatcher()
    bot = Bot(token=token)
    print("XFI Guard Bot: polling запущен", flush=True)
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
