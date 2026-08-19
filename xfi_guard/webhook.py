"""Run the XFI Guard Telegram bot through an HTTPS webhook behind Nginx.

Nginx terminates TLS. This process listens only on localhost and validates the
Telegram secret header through aiogram's SimpleRequestHandler.
"""
from __future__ import annotations

import logging
import os
import secrets

from aiohttp import web
from aiogram import Bot
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from .bot import build_dispatcher

LOG = logging.getLogger("xfi_guard.webhook")

HOST = os.getenv("XFI_GUARD_WEBHOOK_HOST", "127.0.0.1")
PORT = int(os.getenv("XFI_GUARD_WEBHOOK_PORT", "8080"))
PATH = os.getenv("XFI_GUARD_WEBHOOK_PATH", "/xfi-guard/webhook")
PUBLIC_URL = os.getenv("XFI_GUARD_WEBHOOK_URL", "").rstrip("/")
SECRET = os.getenv("XFI_GUARD_WEBHOOK_SECRET", "")
TOKEN = os.getenv("XFI_GUARD_BOT_TOKEN", "")


def _validate_config() -> None:
    if not TOKEN:
        raise RuntimeError("XFI_GUARD_BOT_TOKEN is required")
    if not PUBLIC_URL.startswith("https://"):
        raise RuntimeError("XFI_GUARD_WEBHOOK_URL must start with https://")
    if not SECRET:
        raise RuntimeError("XFI_GUARD_WEBHOOK_SECRET is required")
    if len(SECRET) < 16:
        raise RuntimeError("XFI_GUARD_WEBHOOK_SECRET must be at least 16 characters")
    if not PATH.startswith("/"):
        raise RuntimeError("XFI_GUARD_WEBHOOK_PATH must start with /")


async def _on_startup(bot: Bot) -> None:
    await bot.set_webhook(
        url=f"{PUBLIC_URL}{PATH}",
        secret_token=SECRET,
        allowed_updates=["message", "callback_query"],
        drop_pending_updates=False,
    )
    info = await bot.get_webhook_info()
    LOG.info("Telegram webhook configured: url=%s pending=%s", info.url, info.pending_update_count)


async def _on_shutdown(bot: Bot) -> None:
    # Do not delete the webhook on a normal process restart. Telegram can keep
    # delivering updates while systemd restarts the process.
    LOG.info("XFI Guard webhook shutdown")


def main() -> None:
    _validate_config()
    logging.basicConfig(level=os.getenv("XFI_GUARD_LOG_LEVEL", "INFO"))
    dp = build_dispatcher()
    bot = Bot(token=TOKEN)
    dp.startup.register(_on_startup)
    dp.shutdown.register(_on_shutdown)

    app = web.Application()
    handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        handle_in_background=True,
        secret_token=SECRET,
    )
    handler.register(app, path=PATH)
    setup_application(app, dp, bot=bot)

    LOG.info("Starting XFI Guard webhook listener on %s:%s%s", HOST, PORT, PATH)
    web.run_app(app, host=HOST, port=PORT)


if __name__ == "__main__":
    main()
