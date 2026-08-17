"""Admin Telegram bot for XFI Guard configuration."""

from __future__ import annotations

import asyncio
import os

from .gemini_store import DEFAULT_PATH, DEFAULT_MODEL, load, save

try:
    from aiogram import Bot, Dispatcher, F
    from aiogram.filters import Command
    from aiogram.types import Message
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


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher()

    @dp.message(Command("gemini"))
    async def gemini_help(message: Message) -> None:
        if not is_admin(message):
            return
        await message.answer(
            "Gemini settings:\n"
            "/gemini_key — set API key (bot will delete the key message)\n"
            "/gemini_model <model> — set model\n"
            "/gemini_status — show status\n"
            f"Default model: {DEFAULT_MODEL}"
        )

    @dp.message(Command("gemini_key"))
    async def gemini_key(message: Message) -> None:
        if not is_admin(message):
            return
        args = message.text.partition(" ")[2].strip() if message.text else ""
        if args:
            await message.delete()
            save(args, load().get("model", DEFAULT_MODEL))
            await message.answer("Gemini API key сохранён в защищённом локальном хранилище.")
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
        await message.answer(f"Gemini model установлен: {model}")

    @dp.message(Command("gemini_status"))
    async def gemini_status(message: Message) -> None:
        if not is_admin(message):
            return
        current = load()
        key = current.get("api_key", "")
        await message.answer(f"Gemini: {'ON' if key else 'OFF'}\nModel: {current.get('model', DEFAULT_MODEL)}\nKey: {mask_key(key) if key else 'not configured'}\nStore: {DEFAULT_PATH}")

    @dp.message(F.text)
    async def secret_message(message: Message) -> None:
        if not is_admin(message):
            return
        if message.text and message.text.startswith("AIza"):
            current = load()
            save(message.text.strip(), current.get("model", DEFAULT_MODEL))
            await message.delete()
            await message.answer("Gemini API key сохранён. Ключ не отображается в ответе.")

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
