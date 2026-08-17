"""Admin Telegram bot with XFI Guard controls and AI Security Center."""

from __future__ import annotations

import asyncio
import os

from .ai import AIAnalyzer
from .ai_store import load as load_ai, save as save_ai
from .checks import collect_basic_checks
from .events import parse_file
from .security import collect_security_checks
from .security_center import ai_report, summarize
from .vpn import collect_vpn_checks

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup

TOKEN = os.getenv("XFI_GUARD_BOT_TOKEN")
ADMIN_IDS = {int(value) for value in os.getenv("XFI_GUARD_ADMIN_IDS", "").split(",") if value.strip().isdigit()}

class SetupStates(StatesGroup):
    waiting_provider = State()
    waiting_gemini_key = State()
    waiting_groq_key = State()
    waiting_gemini_model = State()
    waiting_groq_model = State()


def is_admin(message: Message) -> bool:
    return bool(message.from_user and message.from_user.id in ADMIN_IDS)


def mask_key(key: str) -> str:
    return key[:4] + "…" + key[-4:] if len(key) >= 8 else ("configured" if key else "не настроен")


def main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📊 Статус"), KeyboardButton(text="🔐 Безопасность")],
        [KeyboardButton(text="🛡 Fail2Ban"), KeyboardButton(text="🔥 UFW")],
        [KeyboardButton(text="🌐 VPN/Xray"), KeyboardButton(text="📋 События")],
        [KeyboardButton(text="🤖 AI"), KeyboardButton(text="🧠 AI Security Center")],
        [KeyboardButton(text="🔄 Проверка сейчас"), KeyboardButton(text="❓ Помощь")],
    ], resize_keyboard=True, is_persistent=True)


def ai_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🟢 Gemini"), KeyboardButton(text="🔵 Groq")],
        [KeyboardButton(text="🔀 Выбрать AI")],
        [KeyboardButton(text="🔑 Gemini API key"), KeyboardButton(text="🔑 Groq API key")],
        [KeyboardButton(text="🧠 Gemini модель"), KeyboardButton(text="🧠 Groq модель")],
        [KeyboardButton(text="🧪 Проверить AI"), KeyboardButton(text="ℹ️ AI статус")],
        [KeyboardButton(text="⬅️ Главное меню")],
    ], resize_keyboard=True)


def security_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📊 Анализ 24 часа")],
        [KeyboardButton(text="🚨 Топ атакующих IP")],
        [KeyboardButton(text="🤖 AI анализ сводки")],
        [KeyboardButton(text="🔄 Обновить")],
        [KeyboardButton(text="⬅️ Главное меню")],
    ], resize_keyboard=True)


def format_results(results: list) -> str:
    return "\n".join(f"{getattr(x,'status','unknown').upper()}: {x.name} — {x.message}" for x in results)[:3800] or "Нет данных."


def recent_events() -> list:
    from .config import load_config
    cfg = load_config()
    return parse_file(cfg.ssh_log, "ssh") + parse_file(cfg.fail2ban_log, "fail2ban")


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())

    @dp.message(Command("start"))
    async def start(message: Message, state: FSMContext):
        await state.clear()
        if is_admin(message): await message.answer("XFI Guard — панель управления", reply_markup=main_keyboard())

    @dp.message(Command("status"))
    @dp.message(F.text == "📊 Статус")
    async def status(message: Message):
        if is_admin(message): await message.answer("📊 XFI Guard\n\n" + format_results(collect_basic_checks()+collect_security_checks()+collect_vpn_checks()), reply_markup=main_keyboard())

    @dp.message(Command("security"))
    @dp.message(F.text == "🔐 Безопасность")
    async def security(message: Message):
        if is_admin(message): await message.answer("🔐 Security\n\n" + format_results(collect_security_checks()), reply_markup=main_keyboard())

    @dp.message(Command("fail2ban"))
    @dp.message(F.text == "🛡 Fail2Ban")
    async def fail2ban(message: Message):
        if is_admin(message): await message.answer("🛡 Fail2Ban\n\n" + format_results([x for x in collect_security_checks() if x.name == "fail2ban"]), reply_markup=main_keyboard())

    @dp.message(Command("ufw"))
    @dp.message(F.text == "🔥 UFW")
    async def ufw(message: Message):
        if is_admin(message): await message.answer("🔥 UFW\n\n" + format_results([x for x in collect_security_checks() if x.name == "ufw"]), reply_markup=main_keyboard())

    @dp.message(Command("vpn"))
    @dp.message(F.text == "🌐 VPN/Xray")
    async def vpn(message: Message):
        if is_admin(message): await message.answer("🌐 VPN/Xray\n\n" + format_results(collect_vpn_checks()), reply_markup=main_keyboard())

    @dp.message(F.text == "📋 События")
    async def events(message: Message):
        if is_admin(message):
            items = recent_events()[-15:]
            text = "\n".join(f"{e.severity.upper()} | {e.event_type} | {e.ip or '-'} | {e.user or '-'}" for e in items) or "Нет событий."
            await message.answer("📋 Последние события\n\n" + text, reply_markup=main_keyboard())

    @dp.message(Command("check"))
    @dp.message(F.text == "🔄 Проверка сейчас")
    async def check(message: Message):
        if is_admin(message): await message.answer("🔄 Проверка\n\n" + format_results(collect_basic_checks()+collect_security_checks()+collect_vpn_checks()), reply_markup=main_keyboard())

    @dp.message(F.text == "🤖 AI")
    async def ai_menu(message: Message):
        if is_admin(message):
            cfg=load_ai(); await message.answer(f"AI: {cfg.get('provider','gemini').upper()}\nGemini: {mask_key(cfg.get('gemini_key',''))} / {cfg.get('gemini_model','gemini-2.5-pro')}\nGroq: {mask_key(cfg.get('groq_key',''))} / {cfg.get('groq_model','llama-3.3-70b-versatile')}", reply_markup=ai_keyboard())

    @dp.message(F.text == "🧠 AI Security Center")
    async def security_center(message: Message):
        if is_admin(message): await message.answer("🧠 AI Security Center", reply_markup=security_keyboard())

    @dp.message(F.text.in_({"📊 Анализ 24 часа", "🚨 Топ атакующих IP", "🤖 AI анализ сводки", "🔄 Обновить"}))
    async def center_action(message: Message):
        if not is_admin(message): return
        events = recent_events()
        summary = summarize(events, 24)
        if message.text == "📊 Анализ 24 часа":
            text = f"📊 За 24 часа\nСобытий: {summary['events']}\nУникальных IP: {summary['unique_ips']}\nCritical: {summary['critical']}\nWarning: {summary['warning']}"
        elif message.text == "🚨 Топ атакующих IP":
            top = "\n".join(f"{ip}: {count}" for ip, count in summary["top_ips"]) or "Нет IP."
            text = "🚨 Топ IP\n\n" + top
        elif message.text == "🤖 AI анализ сводки":
            text = "🤖 AI анализ\n\n" + (ai_report(events) or "AI не настроен или не ответил.")
        else:
            text = "🔄 Обновлено\n\n" + f"Событий: {summary['events']}\nУникальных IP: {summary['unique_ips']}"
        await message.answer(text[:3900], reply_markup=security_keyboard())

    @dp.message(F.text.in_({"🟢 Gemini", "🔵 Groq", "🔀 Выбрать AI"}))
    async def choose_provider(message: Message, state: FSMContext):
        if not is_admin(message): return
        if message.text == "🟢 Gemini": provider="gemini"
        elif message.text == "🔵 Groq": provider="groq"
        else:
            await state.set_state(SetupStates.waiting_provider); await message.answer("Введите: gemini или groq", reply_markup=ai_keyboard()); return
        cfg=load_ai(); cfg["provider"]=provider; save_ai(cfg); await message.answer(f"AI провайдер: {provider.upper()}", reply_markup=ai_keyboard())

    @dp.message(SetupStates.waiting_provider)
    async def receive_provider(message: Message, state: FSMContext):
        if not is_admin(message): return
        provider=(message.text or "").strip().lower()
        if provider not in {"gemini","groq"}: await message.answer("Введите только gemini или groq"); return
        cfg=load_ai(); cfg["provider"]=provider; save_ai(cfg); await state.clear(); await message.answer(f"AI провайдер: {provider.upper()}", reply_markup=ai_keyboard())

    async def ask_key(message: Message, state: FSMContext, provider: str):
        if is_admin(message): await state.set_state(SetupStates.waiting_gemini_key if provider=="gemini" else SetupStates.waiting_groq_key); await message.answer(f"Отправьте {provider} API key. Сообщение будет удалено.")
    @dp.message(F.text == "🔑 Gemini API key")
    async def gemini_key(message: Message, state: FSMContext): await ask_key(message,state,"gemini")
    @dp.message(F.text == "🔑 Groq API key")
    async def groq_key(message: Message, state: FSMContext): await ask_key(message,state,"groq")

    async def save_key(message: Message, state: FSMContext, provider: str):
        if not is_admin(message): return
        key=(message.text or "").strip()
        if len(key)<20: await message.answer("Ключ выглядит некорректным."); return
        cfg=load_ai(); cfg["gemini_key" if provider=="gemini" else "groq_key"]=key; save_ai(cfg); await state.clear()
        try: await message.delete()
        except Exception: pass
        await message.answer(f"{provider.upper()} API key сохранён.", reply_markup=ai_keyboard())
    @dp.message(SetupStates.waiting_gemini_key)
    async def save_gemini(message: Message,state:FSMContext): await save_key(message,state,"gemini")
    @dp.message(SetupStates.waiting_groq_key)
    async def save_groq(message: Message,state:FSMContext): await save_key(message,state,"groq")

    @dp.message(F.text == "🧠 Gemini модель")
    async def gemini_model(message: Message,state:FSMContext):
        if is_admin(message): await state.set_state(SetupStates.waiting_gemini_model); await message.answer("Введите Gemini model")
    @dp.message(F.text == "🧠 Groq модель")
    async def groq_model(message: Message,state:FSMContext):
        if is_admin(message): await state.set_state(SetupStates.waiting_groq_model); await message.answer("Введите Groq model")
    async def save_model(message: Message,state:FSMContext,provider:str):
        if not is_admin(message): return
        model=(message.text or "").strip()
        if not model or any(ch.isspace() for ch in model): await message.answer("Некорректное имя модели"); return
        cfg=load_ai(); cfg["gemini_model" if provider=="gemini" else "groq_model"]=model; save_ai(cfg); await state.clear(); await message.answer(f"Модель {provider.upper()}: {model}", reply_markup=ai_keyboard())
    @dp.message(SetupStates.waiting_gemini_model)
    async def save_gm(message: Message,state:FSMContext): await save_model(message,state,"gemini")
    @dp.message(SetupStates.waiting_groq_model)
    async def save_gr(message: Message,state:FSMContext): await save_model(message,state,"groq")

    @dp.message(F.text == "🧪 Проверить AI")
    async def test_ai(message: Message):
        if is_admin(message):
            a=AIAnalyzer(); result=a.analyze({"event_type":"manual_test","severity":"warning","message":"XFI Guard AI connectivity test"}); await message.answer("🧪 AI test\n\n"+(result or "AI API не вернул результат."),reply_markup=ai_keyboard())
    @dp.message(F.text == "ℹ️ AI статус")
    async def ai_status(message: Message):
        if is_admin(message):
            cfg=load_ai(); a=AIAnalyzer(); await message.answer(f"Провайдер: {cfg.get('provider','gemini').upper()}\nАктивен: {'YES' if a.enabled() else 'NO'}\nGemini: {mask_key(cfg.get('gemini_key',''))}\nGroq: {mask_key(cfg.get('groq_key',''))}",reply_markup=ai_keyboard())

    @dp.message(F.text == "⬅️ Главное меню")
    async def back(message: Message,state:FSMContext): await state.clear(); await message.answer("XFI Guard — панель управления",reply_markup=main_keyboard())
    @dp.message(Command("help"))
    @dp.message(F.text == "❓ Помощь")
    async def help_message(message: Message):
        if is_admin(message): await message.answer("Все функции доступны кнопками.",reply_markup=main_keyboard())
    return dp

async def main():
    if not TOKEN or not ADMIN_IDS: raise RuntimeError("XFI_GUARD_BOT_TOKEN and XFI_GUARD_ADMIN_IDS are required")
    await build_dispatcher().start_polling(Bot(TOKEN))

if __name__ == "__main__": asyncio.run(main())
