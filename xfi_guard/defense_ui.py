"""Telegram UI for Auto Defense 2.0 with manual IP firewall controls."""
from __future__ import annotations

import os

from aiogram import F, Dispatcher
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup

from .auto_defense import confirm_block, confirm_unblock, history
from .attack_surface import collect_attack_surface
from .firewall import list_blocked_ips, validate_public_ip


class DefenseStates(StatesGroup):
    block_ip = State()
    unblock_ip = State()


def _admin(message) -> bool:
    ids = {int(v) for v in os.getenv("XFI_GUARD_ADMIN_IDS", "").split(",") if v.strip().isdigit()}
    return bool(message.from_user and message.from_user.id in ids)


def _kb(rows):
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=x) for x in row] for row in rows],
        resize_keyboard=True,
        is_persistent=True,
    )


def defense_menu():
    return _kb([
        ["🔴 Заблокировать IP", "🟢 Разблокировать IP"],
        ["📋 Заблокированные IP"],
        ["🧮 Рейтинг угроз", "📜 История защиты"],
        ["⬅️ Главное меню"],
    ])


def _confirm_keyboard(action: str, ip: str):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"manual:{action}:{ip}"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="manual:cancel"),
    ]])


def _wire_bot_audit() -> None:
    """Route legacy bot helpers through the audited defense layer."""
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

    @dp.message(F.text == "🚫 Блокировка IP")
    async def defense_ip_menu(m, state: FSMContext):
        if not _admin(m):
            return
        await state.clear()
        await m.answer("🚫 Управление блокировкой IP\n\nТолько ручное действие администратора. AI не блокирует IP автоматически.", reply_markup=defense_menu())

    @dp.message(F.text == "🔴 Заблокировать IP")
    async def block_prompt(m, state: FSMContext):
        if not _admin(m): return
        await state.set_state(DefenseStates.block_ip)
        await m.answer("🔴 Введите публичный IPv4 для блокировки:\n\nНапример: 8.8.8.8\n\nДля отмены нажмите «⬅️ Главное меню». ", reply_markup=_kb([["❌ Отмена"], ["⬅️ Главное меню"]]))

    @dp.message(DefenseStates.block_ip)
    async def block_input(m, state: FSMContext):
        if not _admin(m): return
        value=(m.text or "").strip()
        if value in {"❌ Отмена", "⬅️ Главное меню"}:
            await state.clear(); await m.answer("Отменено.", reply_markup=defense_menu()); return
        try: ip=validate_public_ip(value)
        except ValueError as exc:
            await m.answer(f"❌ {exc}\n\nВведите публичный IPv4 ещё раз."); return
        await state.clear()
        await m.answer(f"⚠️ Подтвердите блокировку\n\nIP: {ip}\n\nБудет добавлено правило UFW DENY.", reply_markup=_confirm_keyboard("block",ip))

    @dp.message(F.text == "🟢 Разблокировать IP")
    async def unblock_prompt(m, state: FSMContext):
        if not _admin(m): return
        await state.clear()
        items=list_blocked_ips()
        if not items:
            await m.answer("🟢 Заблокированных публичных IP не найдено.", reply_markup=defense_menu()); return
        rows=[[f"🟢 {ip}"] for ip in items[:40]]
        rows.append(["⬅️ Главное меню"])
        await m.answer("🟢 Выберите IP для разблокировки:", reply_markup=_kb(rows))
        await state.set_state(DefenseStates.unblock_ip)

    @dp.message(DefenseStates.unblock_ip)
    async def unblock_input(m, state: FSMContext):
        if not _admin(m): return
        value=(m.text or "").strip()
        if value == "⬅️ Главное меню":
            await state.clear(); await m.answer("Отменено.", reply_markup=defense_menu()); return
        if value.startswith("🟢 "): value=value[2:].strip()
        try: ip=validate_public_ip(value)
        except ValueError as exc:
            await m.answer(f"❌ {exc}"); return
        if ip not in list_blocked_ips():
            await m.answer("❌ Этот IP сейчас не найден среди блокировок.", reply_markup=defense_menu()); await state.clear(); return
        await state.clear()
        await m.answer(f"⚠️ Подтвердите снятие блокировки\n\nIP: {ip}\n\nПравило UFW DENY будет удалено.", reply_markup=_confirm_keyboard("unblock",ip))

    @dp.callback_query(F.data.startswith("manual:"))
    async def manual_action(callback):
        uid=callback.from_user.id if callback.from_user else 0
        ids={int(v) for v in os.getenv("XFI_GUARD_ADMIN_IDS","").split(",") if v.strip().isdigit()}
        if uid not in ids:
            await callback.answer("Нет доступа", show_alert=True); return
        parts=callback.data.split(":",2)
        if len(parts)<2:
            await callback.answer("Некорректное действие", show_alert=True); return
        if parts[1]=="cancel":
            await callback.answer("Отменено"); await callback.message.edit_reply_markup(reply_markup=None); return
        if len(parts)!=3:
            await callback.answer("Некорректный IP", show_alert=True); return
        action,ip=parts[1],parts[2]
        try:
            if action=="block": ok,message=confirm_block(ip,actor=str(uid),reason="Manual IP block from Telegram")
            elif action=="unblock": ok,message=confirm_unblock(ip,actor=str(uid),reason="Manual IP unblock from Telegram")
            else: ok,message=False,"Неизвестное действие"
        except (ValueError,OSError) as exc: ok,message=False,str(exc)
        await callback.answer("Выполнено" if ok else "Ошибка", show_alert=True)
        try: await callback.message.edit_reply_markup(reply_markup=None)
        except Exception: pass
        await callback.message.answer(("✅ " if ok else "❌ ")+message, reply_markup=defense_menu())

    @dp.message(F.text == "📋 Заблокированные IP")
    async def blocked_list(m):
        if not _admin(m): return
        items=list_blocked_ips()
        text="\n".join(f"• {ip}" for ip in items) if items else "Нет ручных блокировок публичных IP."
        await m.answer("📋 Заблокированные IP\n\n"+text[:3800], reply_markup=defense_menu())

    @dp.message(F.text == "🧮 Рейтинг угроз")
    async def threat_ranking_button(m):
        if not _admin(m): return
        data=collect_attack_surface(); items=[x for x in data.get("ips",[]) if not x.get("blocked")]
        items.sort(key=lambda x:int(x.get("risk_score",0) or 0),reverse=True)
        text="\n".join(f"{i+1}. {x.get('ip')} — {x.get('risk','unknown').upper()} {x.get('risk_score',0)}/100 | {x.get('events',0)} событий" for i,x in enumerate(items[:20])) or "Активных угроз не обнаружено."
        await m.answer("🧮 Рейтинг угроз\n\n"+text, reply_markup=defense_menu())

    @dp.message(Command("threats"))
    async def threats_command(m):
        if not _admin(m): return
        data=collect_attack_surface(); items=[x for x in data.get("ips",[]) if not x.get("blocked")]
        items.sort(key=lambda x:int(x.get("risk_score",0) or 0),reverse=True)
        text="\n".join(f"{i+1}. {x.get('ip')} — {x.get('risk','unknown').upper()} {x.get('risk_score',0)}/100 | {x.get('events',0)} событий" for i,x in enumerate(items[:20])) or "Активных угроз не обнаружено."
        await m.answer("🧮 Рейтинг угроз\n\n"+text, reply_markup=defense_menu())

    @dp.message(F.text == "📜 История защиты")
    async def defense_history_button(m):
        if not _admin(m): return
        items=history(30)
        if not items: text="История защиты пуста."
        else:
            text="\n".join(f"• {x.get('timestamp','')[:19]} | {x.get('action','')} | {x.get('ip','-')} | {x.get('actor','admin')}\n  {x.get('reason','')[:180]}" for x in reversed(items))
        await m.answer("📜 История защиты\n\n"+text[:3800], reply_markup=defense_menu())

    @dp.message(Command("defense_history"))
    async def defense_history_command(m):
        if not _admin(m): return
        await defense_history_button(m)
