"""Secure Telegram callbacks for autonomous threat alerts."""
from __future__ import annotations

import json
from pathlib import Path

from aiogram import F
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from .auto_defense import confirm_block

STATE_FILE = Path("/var/lib/xfi-guard/security_monitor.json")
_pending: dict[int, str] = {}


def _load() -> dict:
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"alerts": []}
    except (OSError, ValueError):
        return {"alerts": []}


def register_alert_callbacks(dp, admin_ids: set[int]):
    @dp.callback_query(F.data.startswith("xfi:block:"))
    async def block_alert(callback: CallbackQuery):
        uid = callback.from_user.id if callback.from_user else 0
        if uid not in admin_ids:
            await callback.answer("Нет доступа", show_alert=True); return
        ip = callback.data.split(":", 2)[2].strip()
        _pending[uid] = ip
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ ПОДТВЕРДИТЬ БЛОКИРОВКУ", callback_data="xfi:confirm")], [InlineKeyboardButton(text="❌ Отмена", callback_data="xfi:cancel")]])
        await callback.answer()
        await callback.message.answer(f"⚠️ Подтверждение защиты\n\nIP: {ip}\n\nПосле подтверждения IP будет добавлен в UFW и действие попадёт в audit history.", reply_markup=keyboard)

    @dp.callback_query(F.data == "xfi:confirm")
    async def confirm_alert(callback: CallbackQuery):
        uid = callback.from_user.id if callback.from_user else 0
        if uid not in admin_ids:
            await callback.answer("Нет доступа", show_alert=True); return
        ip = _pending.pop(uid, "")
        if not ip:
            await callback.answer("Подтверждение истекло", show_alert=True); return
        try:
            ok, message = confirm_block(ip, actor=str(uid), reason="Security Monitor alert confirmed in Telegram")
        except ValueError as exc:
            ok, message = False, str(exc)
        await callback.answer("Заблокировано" if ok else "Ошибка", show_alert=True)
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer(("🛡 IP заблокирован\n\n" if ok else "❌ Блокировка не выполнена\n\n") + f"{ip}\n{message}")

    @dp.callback_query(F.data == "xfi:cancel")
    async def cancel_alert(callback: CallbackQuery):
        uid = callback.from_user.id if callback.from_user else 0
        _pending.pop(uid, None)
        await callback.answer("Отменено")
        await callback.message.edit_reply_markup(reply_markup=None)

    @dp.callback_query(F.data.startswith("xfi:ignore:"))
    async def ignore_alert(callback: CallbackQuery):
        uid = callback.from_user.id if callback.from_user else 0
        if uid not in admin_ids:
            await callback.answer("Нет доступа", show_alert=True); return
        await callback.answer("Угроза отмечена как просмотренная")
        await callback.message.edit_reply_markup(reply_markup=None)

    @dp.callback_query(F.data.startswith("xfi:detail:"))
    async def detail_alert(callback: CallbackQuery):
        uid = callback.from_user.id if callback.from_user else 0
        if uid not in admin_ids:
            await callback.answer("Нет доступа", show_alert=True); return
        alert_id = callback.data.split(":", 2)[2]
        alert = next((x for x in reversed(_load().get("alerts", [])) if x.get("id") == alert_id), None)
        if not alert:
            await callback.answer("Тревога не найдена", show_alert=True); return
        await callback.answer()
        await callback.message.answer(json.dumps(alert, ensure_ascii=False, indent=2)[:3900])
