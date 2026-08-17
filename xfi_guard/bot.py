"""Admin Telegram bot with button-driven XFI Guard controls."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from .checks import collect_basic_checks
from .config import load_config
from .events import parse_file
from .gemini import GeminiAnalyzer
from .gemini_store import DEFAULT_PATH, DEFAULT_MODEL, load, save
from .security import collect_security_checks
from .vpn import collect_vpn_checks

try:
    from aiogram import Bot, Dispatcher, F
    from aiogram.filters import Command
    from aiogram.fsm.context import FSMContext
    from aiogram.fsm.state import State, StatesGroup
    from aiogram.fsm.storage.memory import MemoryStorage
    from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("Install aiogram to run the XFI Guard bot") from exc

TOKEN = os.getenv("XFI_GUARD_BOT_TOKEN")
ADMIN_IDS = {int(value) for value in os.getenv("XFI_GUARD_ADMIN_IDS", "").split(",") if value.strip().isdigit()}
CONFIG_PATH = os.getenv("XFI_GUARD_CONFIG", "config.toml")


class SetupStates(StatesGroup):
    waiting_key = State()
    waiting_model = State()


def is_admin(message: Message) -> bool:
    return bool(message.from_user and message.from_user.id in ADMIN_IDS)


def mask_key(key: str) -> str:
    if len(key) < 8:
        return "configured"
    return key[:4] + "…" + key[-4:]


def main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Статус"), KeyboardButton(text="🔐 Безопасность")],
            [KeyboardButton(text="🛡 Fail2Ban"), KeyboardButton(text="🔥 UFW")],
            [KeyboardButton(text="🌐 VPN/Xray"), KeyboardButton(text="📋 События")],
            [KeyboardButton(text="🤖 Gemini"), KeyboardButton(text="⚙️ Настройки")],
            [KeyboardButton(text="🔄 Проверка сейчас"), KeyboardButton(text="❓ Помощь")],
        ], resize_keyboard=True, is_persistent=True,
    )


def gemini_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔑 Установить Gemini API key")],
            [KeyboardButton(text="🧠 Выбрать модель"), KeyboardButton(text="ℹ️ Gemini status")],
            [KeyboardButton(text="🧪 Тест Gemini"), KeyboardButton(text="⬅️ Главное меню")],
        ], resize_keyboard=True,
    )


def format_results(results: list) -> str:
    lines = []
    for item in results:
        status = getattr(item, "status", "unknown").upper()
        lines.append(f"{status}: {item.name} — {item.message}")
    return "\n".join(lines)[:3800] or "Нет данных."


def read_events(config_path: str) -> str:
    config = load_config(config_path)
    paths = [(config.ssh_log, "SSH"), (config.fail2ban_log, "Fail2Ban")]
    found = []
    for path, source in paths:
        for event in parse_file(path, source.lower())[-10:]:
            found.append(f"[{event.severity.upper()}] {source}: {event.message}")
    return "\n".join(found)[-3800:] if found else "Новых распознанных событий в доступных журналах нет."


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())

    async def require_admin(message: Message) -> bool:
        if not is_admin(message):
            return False
        return True

    async def show_menu(message: Message) -> None:
        if await require_admin(message):
            await message.answer("XFI Guard — панель управления", reply_markup=main_keyboard())

    async def show_gemini(message: Message) -> None:
        if not await require_admin(message):
            return
        current = load()
        key = current.get("api_key", "")
        await message.answer(
            f"Gemini: {'ON' if key else 'OFF'}\nМодель: {current.get('model', DEFAULT_MODEL)}\n"
            f"Ключ: {mask_key(key) if key else 'не настроен'}",
            reply_markup=gemini_keyboard(),
        )

    @dp.message(Command("start"))
    async def start(message: Message, state: FSMContext) -> None:
        await state.clear()
        await show_menu(message)

    @dp.message(Command("help"))
    @dp.message(F.text == "❓ Помощь")
    async def help_command(message: Message) -> None:
        if await require_admin(message):
            await message.answer(
                "Команды полностью доступны кнопками.\n\n"
                "/start /help /status /security /fail2ban /ufw /vpn /events /check\n"
                "/gemini /gemini_key /gemini_model /gemini_status",
                reply_markup=main_keyboard(),
            )

    @dp.message(Command("status"))
    @dp.message(F.text == "📊 Статус")
    async def status(message: Message) -> None:
        if await require_admin(message):
            results = collect_basic_checks() + collect_security_checks() + collect_vpn_checks()
            await message.answer("📊 XFI Guard status\n\n" + format_results(results), reply_markup=main_keyboard())

    @dp.message(Command("security"))
    @dp.message(F.text == "🔐 Безопасность")
    async def security(message: Message) -> None:
        if await require_admin(message):
            await message.answer("🔐 Security\n\n" + format_results(collect_security_checks()), reply_markup=main_keyboard())

    @dp.message(Command("fail2ban"))
    @dp.message(F.text == "🛡 Fail2Ban")
    async def fail2ban(message: Message) -> None:
        if await require_admin(message):
            result = [x for x in collect_security_checks() if x.name == "fail2ban"]
            await message.answer("🛡 Fail2Ban\n\n" + format_results(result), reply_markup=main_keyboard())

    @dp.message(Command("ufw"))
    @dp.message(F.text == "🔥 UFW")
    async def ufw(message: Message) -> None:
        if await require_admin(message):
            result = [x for x in collect_security_checks() if x.name == "ufw"]
            await message.answer("🔥 UFW\n\n" + format_results(result), reply_markup=main_keyboard())

    @dp.message(Command("vpn"))
    @dp.message(F.text == "🌐 VPN/Xray")
    async def vpn(message: Message) -> None:
        if await require_admin(message):
            await message.answer("🌐 VPN/Xray\n\n" + format_results(collect_vpn_checks()), reply_markup=main_keyboard())

    @dp.message(Command("events"))
    @dp.message(F.text == "📋 События")
    async def events(message: Message) -> None:
        if await require_admin(message):
            await message.answer("📋 Последние события\n\n" + read_events(CONFIG_PATH), reply_markup=main_keyboard())

    @dp.message(Command("check"))
    @dp.message(F.text == "🔄 Проверка сейчас")
    async def check(message: Message) -> None:
        if await require_admin(message):
            results = collect_basic_checks() + collect_security_checks() + collect_vpn_checks()
            await message.answer("🔄 Проверка завершена\n\n" + format_results(results), reply_markup=main_keyboard())

    @dp.message(Command("gemini"))
    @dp.message(F.text == "🤖 Gemini")
    async def gemini_help(message: Message) -> None:
        await show_gemini(message)

    @dp.message(Command("gemini_key"))
    async def gemini_key_command(message: Message, state: FSMContext) -> None:
        if not await require_admin(message):
            return
        args = message.text.partition(" ")[2].strip() if message.text else ""
        if args:
            save(args, load().get("model", DEFAULT_MODEL))
            try: await message.delete()
            except Exception: pass
            await message.answer("Gemini API key сохранён.", reply_markup=gemini_keyboard())
            return
        await state.set_state(SetupStates.waiting_key)
        await message.answer("Отправьте API key следующим сообщением. Сообщение будет удалено.", reply_markup=gemini_keyboard())

    @dp.message(F.text == "🔑 Установить Gemini API key")
    async def gemini_key_button(message: Message, state: FSMContext) -> None:
        if await require_admin(message):
            await state.set_state(SetupStates.waiting_key)
            await message.answer("Отправьте Gemini API key следующим сообщением. Оно будет удалено.")

    @dp.message(SetupStates.waiting_key)
    async def receive_gemini_key(message: Message, state: FSMContext) -> None:
        if not await require_admin(message):
            return
        key = (message.text or "").strip()
        if len(key) < 20:
            await message.answer("Ключ выглядит слишком коротким. Отправьте корректный Gemini API key.")
            return
        save(key, load().get("model", DEFAULT_MODEL))
        await state.clear()
        try: await message.delete()
        except Exception: pass
        await message.answer("Gemini API key сохранён в защищённом локальном хранилище.", reply_markup=gemini_keyboard())

    @dp.message(Command("gemini_model"))
    async def gemini_model_command(message: Message, state: FSMContext) -> None:
        if not await require_admin(message):
            return
        model = message.text.partition(" ")[2].strip() if message.text else ""
        if model:
            save(load().get("api_key", ""), model)
            await message.answer(f"Модель Gemini установлена: {model}", reply_markup=gemini_keyboard())
            return
        await state.set_state(SetupStates.waiting_model)
        await message.answer("Введите название модели, например: gemini-2.5-pro")

    @dp.message(F.text == "🧠 Выбрать модель")
    async def gemini_model_button(message: Message, state: FSMContext) -> None:
        if await require_admin(message):
            await state.set_state(SetupStates.waiting_model)
            await message.answer("Введите название модели, например: gemini-2.5-pro")

    @dp.message(SetupStates.waiting_model)
    async def receive_gemini_model(message: Message, state: FSMContext) -> None:
        if not await require_admin(message):
            return
        model = (message.text or "").strip()
        if not model or any(ch.isspace() for ch in model):
            await message.answer("Некорректное имя модели. Пример: gemini-2.5-pro")
            return
        save(load().get("api_key", ""), model)
        await state.clear()
        await message.answer(f"Модель Gemini установлена: {model}", reply_markup=gemini_keyboard())

    @dp.message(Command("gemini_status"))
    @dp.message(F.text == "ℹ️ Gemini status")
    async def gemini_status(message: Message) -> None:
        await show_gemini(message)

    @dp.message(F.text == "🧪 Тест Gemini")
    async def gemini_test(message: Message) -> None:
        if not await require_admin(message):
            return
        analyzer = GeminiAnalyzer()
        if not analyzer.enabled():
            await message.answer("Gemini выключен: сначала задайте API key.", reply_markup=gemini_keyboard())
            return
        result = analyzer.analyze({"event_type": "manual_test", "severity": "warning", "message": "XFI Guard Telegram Gemini connectivity test"})
        await message.answer("🧪 Gemini test\n\n" + (result or "Gemini API не вернул результат."), reply_markup=gemini_keyboard())

    @dp.message(F.text == "⚙️ Настройки")
    async def settings(message: Message) -> None:
        if await require_admin(message):
            config = load_config(CONFIG_PATH)
            await message.answer(
                f"⚙️ Настройки\nИнтервал: {config.interval_seconds}s\n"
                f"Telegram alerts: {'ON' if config.telegram_enabled else 'OFF'}\n"
                f"Gemini: {'ON' if config.gemini_enabled else 'OFF'}\nModel: {config.gemini_model}",
                reply_markup=main_keyboard(),
            )

    @dp.message(F.text == "⬅️ Главное меню")
    async def back(message: Message, state: FSMContext) -> None:
        await state.clear()
        await show_menu(message)

    return dp


async def main() -> None:
    if not TOKEN:
        raise RuntimeError("XFI_GUARD_BOT_TOKEN is not configured")
    if not ADMIN_IDS:
        raise RuntimeError("XFI_GUARD_ADMIN_IDS is not configured")
    bot = Bot(TOKEN)
    await build_dispatcher().start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
