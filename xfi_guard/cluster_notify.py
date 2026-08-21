"""Telegram notifications for Multi-VPS global blocks."""
from __future__ import annotations

import asyncio
import os
from aiogram import Bot


def format_global_block(event: dict, blocked_nodes: list[str]) -> str:
    ip = event.get("ip", "-")
    score = event.get("score", 0)
    risk = str(event.get("risk", "unknown")).upper()
    source = event.get("source_node", event.get("node", "unknown"))
    until = event.get("until", "-")
    providers = event.get("providers", "-")
    return (
        "🚨 XFI GUARD — ГЛОБАЛЬНАЯ БЛОКИРОВКА\n\n"
        f"IP: {ip}\n"
        f"Угроза: {risk}\n"
        f"Рейтинг: {score}/100\n"
        f"Источник: {source}\n"
        f"AI confidence: {event.get('confidence', '-')}\n"
        f"AI: {providers}\n\n"
        "🔒 Заблокирован автоматически без подтверждения.\n"
        "⏱ Срок: 7 дней\n"
        f"До: {until}\n\n"
        "🖥 VPS, применившие блокировку:\n"
        + ("\n".join(f"• {n}" for n in blocked_nodes) if blocked_nodes else "• локальный узел")
    )


async def notify_global_block(event: dict, blocked_nodes: list[str]) -> bool:
    token = os.getenv("XFI_GUARD_BOT_TOKEN", "").strip()
    admins = [int(x) for x in os.getenv("XFI_GUARD_ADMIN_IDS", "").split(",") if x.strip().isdigit()]
    if not token or not admins:
        return False
    bot = Bot(token=token)
    try:
        text = format_global_block(event, blocked_nodes)
        for admin_id in admins:
            await bot.send_message(admin_id, text)
        return True
    finally:
        await bot.session.close()


def notify_global_block_sync(event: dict, blocked_nodes: list[str]) -> bool:
    return asyncio.run(notify_global_block(event, blocked_nodes))
