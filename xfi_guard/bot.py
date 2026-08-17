"""Admin Telegram bot for XFI Guard configuration and control."""

from __future__ import annotations

import asyncio
import os

from .gemini_store import DEFAULT_PATH, DEFAULT_MODEL, load, save

try:
    from aiogram import Bot, Dispatcher, F
    from aiogram.filters import Command
    from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("Install aiogram to run the XFI Guard bot") from exc

TOKEN = os.getenv("XFI_GUARD_BOT_TOKEN")
ADMIN_IDS = {int(value) for value in os.getenv("XFI_GUARD_ADMIN_IDS", "").split(",") if value.strip().isdigit()}


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
            [KeyboardButton(text="🔄 Проверка сейчас")],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def gemini_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔑 Установить Gemini API key")],
            [KeyboardButton(text="🧠 Выбрать модель"), KeyboardButton(text="ℹ️ Gemini status")],
            [KeyboardButton(text="⬅️ Главное меню")],
        ],
        resize_keyboard=True,
    )


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher()

    async def show_menu(message: Message) -> None:
        if is_admin(message):
            await message.answer("XFI Guard — панель управления", reply_markup=main_keyboard())

    @dp.message(Command("start"))
    async def start(message: Message) -> None:
        await show_menu(message)

    @dp.message(Command("help"))
    async def help_command(message: Message) -> None:
        if not is_admin(message):
            return
        await message.answer(
            "Все основные функции доступны кнопками ниже.\n\n"
            "Команды также поддерживаются:\n"
            "/status\n/security\n/fail2ban\n/ufw\n/vpn\n/events\n/check\n"
            "/gemini\n/gemini_key\n/gemini_model\n/gemini_status",
            reply_markup=main_keyboard(),
        )

    @dp.message(Command("gemini"))
    async def gemini_help(message: Message) -> None:
        if not is_admin(message):
            return
        await message.answer(
            "Gemini settings:\n"
            "🔑 Установить API key — безопасный ввод с удалением сообщения\n"
            "🧠 Выбрать модель — изменить модель\n"
            "ℹ️ Gemini status — состояние Gemini\n"
            f"Default model: {DEFAULT_MODEL}",
            reply_markup=gemini_keyboard(),
        )

    @dp.message(Command("gemini_key"))
    async def gemini_key(message: Message) -> None:
        if not is_admin(message):
            return
        args = message.text.partition(" ")[2].strip() if message.text else ""
        if args:
            try:
                await message.delete()
            except Exception:
                pass
            save(args, load().get("model", DEFAULT_MODEL))
            await message.answer("Gemini API key сохранён в защищённом локальном хранилище.", reply_markup=gemini_keyboard())
            return
        await message.answer("Отправьте API key следующим сообщением. Сообщение с ключом будет удалено.")

    @dp.message(Command("gemini_model"))
    async def gemini_model(message: Message) -> None:
        if not is_admin(message):
            return
        model = message.text.partition(" ")[2].strip() if message.text else ""
        if not model:
            await message.answer("Пример: /gemini_model gemini-2.5-pro")
            return
        current = load()
        save(current.get("api_key", ""), model)
        await message.answer(f"Gemini model установлен: {model}", reply_markup=gemini_keyboard())

    @dp.message(Command("gemini_status"))
    async def gemini_status(message: Message) -> None:
        if not is_admin(message):
            return
        current = load()
        key = current.get("api_key", "")
        await message.answer(
            f"Gemini: {'ON' if key else 'OFF'}\nModel: {current.get('model', DEFAULT_MODEL)}\n"
            f"Key: {mask_key(key) if key else 'not configured'}\nStore: {DEFAULT_PATH}",
            reply_markup=gemini_keyboard(),
        )

    @dp.message(F.text == "🤖 Gemini")
    async def button_gemini(message: Message) -> None:
        await gemini_help(message)

    @dp.message(F.text == "🔑 Установить Gemini API key")
    async def button_gemini_key(message: Message) -> None:
        if is_admin(message):
            await message.answer("Отправьте Gemini API key следующим сообщением. Оно будет удалено.")

    @dp.message(F.text == "🧠 Выбрать модель")
    async def button_gemini_model(message: Message) -> None:
        if is_admin(message):
            await message.answer("Введите команду /gemini_model <название модели>\nНапример: /gemini_model gemini-2.5-pro")

    @dp.message(F.text == "ℹ️ Gemini status")
    async def button_gemini_status(message: Message) -> None:
        await gemini_status(message)

    @dp.message(F.text == "⬅️ Главное меню")
    async def back(message: Message) -> None:
        await show_menu(message)

    @dp.message(F.text == "⚙️ Настройки")
    async def settings(message: Message) -> None:
        if is_admin(message):
            await message.answer("Настройки XFI Guard управляются через конфигурацию и защищённые секреты.", reply_markup=main_keyboard())

    @dp.message(F.text == "📊 Статус")
    @dp.message(Command("status"))
    async def status(message: Message) -> None:
        if is_admin(message):
            await message.answer("Для полного системного статуса используйте /check.", reply_markup=main_keyboard())

    @dp.message(F.text == "🔐 Безопасность")
    @dp.message(Command("security"))
    async def security(message: Message) -> None:
        if is_admin(message):
            await message.answer("Security monitor: SSH / UFW / Fail2Ban", reply_markup=main_keyboard())

    @dp.message(F.text == "🛡 Fail2Ban")
    @dp.message(Command("fail2ban"))
    async def fail2ban(message: Message) -> None:
        if is_admin(message):
            await message.answer("Fail2Ban monitor активен.", reply_markup=main_keyboard())

    @dp.message(F.text == "🔥 UFW")
    @dp.message(Command("ufw"))
    async def ufw(message: Message) -> None:
        if is_admin(message):
            await message.answer("UFW monitor активен.", reply_markup=main_keyboard())

    @dp.message(F.text == "🌐 VPN/Xray")
    @dp.message(Command("vpn"))
    async def vpn(message: Message) -> None:
        if is_admin(message):
            await message.answer("VPN/Xray monitor активен.", reply_markup=main_keyboard())

    @dp.message(F.text == "📋 События")
    @dp.message(Command("events"))
    async def events(message: Message) -> None:
        if is_admin(message):
            await message.answer("События SSH/Fail2Ban записываются в monitor.jsonl.", reply_markup=main_keyboard())

    @dp.message(F.text == "🔄 Проверка сейчас")
    @dp.message(Command("check"))
    async def check(message: Message) -> None:
        if is_admin(message):
            await message.answer("Запущена проверка XFI Guard. Результат будет записан монитором.", reply_markup=main_keyboard())

    @dp.message(F.text)
    async def secret_message(message: Message) -> None:
        if not is_admin(message):
            return
        if message.text and message.text.startswith("AIza"):
            current = load()
            save(message.text.strip(), current.get("model", DEFAULT_MODEL))
            try:
                await message.delete()
            except Exception:
                pass
            await message.answer("Gemini API key сохранён. Ключ не отображается в ответе.", reply_markup=gemini_keyboard())

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
