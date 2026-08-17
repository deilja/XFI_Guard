"""Telegram UI for Auto Defense 2.0. Read-only dashboards plus safe history."""
from __future__ import annotations

import os

from aiogram import F, Dispatcher
from aiogram.filters import Command
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from .auto_defense import confirm_block, confirm_unblock, history
from .attack_surface import collect_attack_surface


def _admin(message) -> bool:
    ids = {int(v) for v in os.getenv("XFI_GUARD_ADMIN_IDS", "").split(",") if v.strip().isdigit()}
    return bool(message.from_user and message.from_user.id in ids)


def _kb(rows):
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=x) for x in row] for row in rows],
        resize_keyboard=True,
        is_persistent=True,
    )


def _wire_bot_audit() -> None:
    """Route existing bot confirmations through the audited defense layer."""
    try:
        from . import bot as bot_module
    except Exception:
        return
    if getattr(bot_module, "_xfi_defense_audit_wired", False):
        return

    def audited_block(ip: str):
        return confirm_block(ip, actor="telegram_admin", reason="Telegram administrator confirmation")

    def audited_unblock(ip: str):
        return confirm_unblock(ip, actor="telegram_admin", reason="Telegram administrator confirmation")

    bot_module.block_ip = audited_block
    bot_module.unblock_ip = audited_unblock
    bot_module._xfi_defense_audit_wired = True


def install_defense_handlers(dp: Dispatcher) -> None:
    if getattr(dp, "_xfi_defense_ui_installed", False):
        return
    dp._xfi_defense_ui_installed = True
    _wire_bot_audit()

    @dp.message(Command("threats"))
    async def threats_command(m):
        if not _admin(m):
            return
        data = collect_attack_surface()
        items = [x for x in data.get("ips", []) if not x.get("blocked")]
        items.sort(key=lambda x: int(x.get("risk_score", 0) or 0), reverse=True)
        if not items:
            text = "Активных угроз не обнаружено."
        else:
            text = "\n".join(
                f"{i + 1}. {x.get('ip')} — {x.get('risk', 'unknown').upper()} "
                f"{x.get('risk_score', 0)}/100 | {x.get('events', 0)} событий"
                for i, x in enumerate(items[:20])
            )
        await m.answer("🧮 Рейтинг угроз\n\n" + text, reply_markup=_kb([["⬅️ Главное меню"]]))

    @dp.message(Command("defense_history"))
    async def defense_history_command(m):
        if not _admin(m):
            return
        items = history(30)
        if not items:
            text = "История защиты пуста."
        else:
            lines = []
            for item in reversed(items):
                lines.append(
                    f"• {item.get('timestamp', '')[:19]} | {item.get('action', '')} | "
                    f"{item.get('ip', '-')} | {item.get('actor', 'admin')}\n"
                    f"  {item.get('reason', '')[:180]}"
                )
            text = "\n".join(lines)
        await m.answer("📜 История защиты\n\n" + text[:3800], reply_markup=_kb([["⬅️ Главное меню"]]))

    @dp.message(F.text == "📜 История защиты")
    async def defense_history_button(m):
        await defense_history_command(m)

    @dp.message(F.text == "🧮 Рейтинг угроз")
    async def threat_ranking_button(m):
        await threats_command(m)
