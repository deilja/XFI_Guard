"""Telegram UI for Auto Defense 2.0 with manual IP firewall controls."""
from __future__ import annotations

import os
import threading
import time

from aiogram import F, Dispatcher
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup

from .auto_defense import confirm_block, confirm_unblock, history
from .attack_surface import collect_attack_surface
from .firewall import list_blocked_ips, validate_public_ip

_ACTION_LOCK = threading.Lock()
_ACTIONS = {}
_ACTION_TTL = 30


class DefenseStates(StatesGroup):
    block_ip = State()
    unblock_ip = State()


def _action_once(key: str) -> bool:
    now = time.monotonic()
    with _ACTION_LOCK:
        for k, ts in list(_ACTIONS.items()):
            if now - ts > _ACTION_TTL:
                _ACTIONS.pop(k, None)
        if key in _ACTIONS:
            return False
        _ACTIONS[key] = now
        return True


def _admin(message) -> bool:
    ids = {int(v) for v in os.getenv("XFI_GUARD_ADMIN_IDS", "").split(",") if v.strip().isdigit()}
    return bool(message.from_user and message.from_user.id in ids)


def _kb(rows):
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=x) for x in row] for row in rows], resize_keyboard=True, is_persistent=True)


def defense_menu():
    return _kb([
        ["🔴 Заблокировать IP", "🟢 Разблокировать IP"],
        ["📋 Заблокированные IP"],
        ["🚨 Заблокировать все критические"],
        ["🧮 Рейтинг угроз", "📜 История защиты"],
        ["🔄 Обновить список", "⬅️ Главное меню"],
    ])


def _confirm_keyboard(action: str, ip: str):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"manual:{action}:{ip}"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="manual:cancel"),
    ]])


def _threat_items():
    data = collect_attack_surface()
    blocked = set(list_blocked_ips())
    items = []
    for item in data.get("ips", []):
        ip = str(item.get("ip", "")).strip()
        if not ip or ip in blocked:
            continue
        item = dict(item)
        item["risk_score"] = int(item.get("risk_score", 0) or 0)
        items.append(item)
    return sorted(items, key=lambda x: x["risk_score"], reverse=True)


def _critical_candidates():
    return [x for x in _threat_items() if str(x.get("risk", "")).lower() == "critical" or x["risk_score"] >= 80]


def _defense_text():
    blocked = list_blocked_ips()
    critical = _critical_candidates()
    lines = ["🚫 Управление блокировкой IP", "", f"🔒 Заблокировано: {len(blocked)}", f"🚨 Критических к блокировке: {len(critical)}", ""]
    if blocked:
        lines.append("🔒 Текущие блокировки:")
        lines.extend(f"• {ip}" for ip in blocked[:15])
        if len(blocked) > 15: lines.append(f"… ещё {len(blocked) - 15}")
        lines.append("")
    if critical:
        lines.append("🚨 Критические угрозы:")
        lines.extend(f"• {x.get('ip')} — {str(x.get('risk','critical')).upper()} {x['risk_score']}/100" for x in critical[:15])
    else:
        lines.append("✅ Критических угроз для блокировки нет.")
    return "\n".join(lines)[:3900]


def _defense_inline():
    critical = _critical_candidates()
    rows = []
    if critical:
        rows.append([InlineKeyboardButton(text=f"🚨 Заблокировать все критические ({len(critical)})", callback_data="manual:block_all_critical")])
        for item in critical[:8]:
            ip = str(item.get("ip", "")); score = item["risk_score"]
            if ip: rows.append([InlineKeyboardButton(text=f"🚫 {ip} — {score}/100", callback_data=f"manual:block:{ip}")])
    rows.append([InlineKeyboardButton(text="🔄 Обновить", callback_data="manual:refresh_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _threat_inline(items):
    rows = []
    if items:
        rows.append([InlineKeyboardButton(text=f"🚨 Заблокировать все угрозы ({len(items)})", callback_data="manual:block_all_threats")])
        critical = [x for x in items if str(x.get("risk", "")).lower() == "critical" or x["risk_score"] >= 80]
        if critical:
            rows.append([InlineKeyboardButton(text=f"🚨 Только критические ({len(critical)})", callback_data="manual:block_all_critical")])
        for item in items[:20]:
            ip = str(item.get("ip", "")); score = item["risk_score"]
            risk = str(item.get("risk", "unknown")).upper()
            if ip:
                rows.append([InlineKeyboardButton(text=f"🚫 {ip} — {risk} {score}/100", callback_data=f"manual:block:{ip}")])
    rows.append([InlineKeyboardButton(text="🔄 Обновить угрозы", callback_data="manual:refresh_threats")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _wire_bot_audit() -> None:
    try:
        from . import bot as bot_module
    except Exception:
        return
    if getattr(bot_module, "_xfi_defense_audit_wired", False):
        return
    def audited_block(ip: str): return confirm_block(ip, actor="telegram_admin", reason="Telegram administrator confirmation")
    def audited_unblock(ip: str): return confirm_unblock(ip, actor="telegram_admin", reason="Telegram administrator confirmation")
    bot_module.block_ip = audited_block
    bot_module.unblock_ip = audited_unblock
    bot_module._xfi_defense_audit_wired = True


def install_defense_handlers(dp: Dispatcher) -> None:
    if getattr(dp, "_xfi_defense_ui_installed", False): return
    dp._xfi_defense_ui_installed = True
    _wire_bot_audit()

    @dp.message(F.text == "🚫 Блокировка IP")
    async def defense_ip_menu(m, state: FSMContext):
        if not _admin(m): return
        await state.clear(); await m.answer(_defense_text(), reply_markup=defense_menu())

    @dp.message(F.text == "🔴 Заблокировать IP")
    async def block_prompt(m, state: FSMContext):
        if not _admin(m): return
        await state.set_state(DefenseStates.block_ip)
        await m.answer("🔴 Введите публичный IPv4 для блокировки:\n\nНапример: 8.8.8.8\n\nДля отмены нажмите «⬅️ Главное меню».", reply_markup=_kb([["❌ Отмена"], ["⬅️ Главное меню"]]))

    @dp.message(DefenseStates.block_ip)
    async def block_input(m, state: FSMContext):
        if not _admin(m): return
        value=(m.text or "").strip()
        if value in {"❌ Отмена", "⬅️ Главное меню"}:
            await state.clear(); await m.answer(_defense_text(), reply_markup=defense_menu()); return
        try: ip=validate_public_ip(value)
        except ValueError as exc: await m.answer(f"❌ {exc}\n\nВведите публичный IPv4 ещё раз."); return
        await state.clear(); await m.answer(f"⚠️ Подтвердите блокировку\n\nIP: {ip}\n\nБудет добавлено правило UFW DENY.", reply_markup=_confirm_keyboard("block",ip))

    @dp.message(F.text == "🟢 Разблокировать IP")
    async def unblock_prompt(m, state: FSMContext):
        if not _admin(m): return
        items=list_blocked_ips(); await state.clear()
        if not items: await m.answer(_defense_text(), reply_markup=defense_menu()); return
        await m.answer("🟢 Выберите IP для разблокировки:", reply_markup=_kb([[f"🟢 {ip}"] for ip in items[:40]]+[["⬅️ Главное меню"]])); await state.set_state(DefenseStates.unblock_ip)

    @dp.message(DefenseStates.unblock_ip)
    async def unblock_input(m, state: FSMContext):
        if not _admin(m): return
        value=(m.text or "").strip()
        if value == "⬅️ Главное меню": await state.clear(); await m.answer(_defense_text(), reply_markup=defense_menu()); return
        if value.startswith("🟢 "): value=value[2:].strip()
        try: ip=validate_public_ip(value)
        except ValueError as exc: await m.answer(f"❌ {exc}"); return
        if ip not in list_blocked_ips(): await state.clear(); await m.answer("❌ Этот IP сейчас не найден среди блокировок.", reply_markup=defense_menu()); return
        await state.clear(); await m.answer(f"⚠️ Подтвердите снятие блокировки\n\nIP: {ip}\n\nПравило UFW DENY будет удалено.", reply_markup=_confirm_keyboard("unblock",ip))

    @dp.message(F.text == "🚨 Заблокировать все критические")
    async def block_all_critical(m, state: FSMContext):
        if not _admin(m): return
        await state.clear(); items=_critical_candidates()
        if not items: await m.answer(_defense_text(), reply_markup=defense_menu()); return
        preview="\n".join(f"• {x.get('ip')} — {x.get('risk','critical').upper()} {x['risk_score']}/100" for x in items[:20])
        await m.answer(f"⚠️ Подтвердите массовую блокировку\n\nБудут заблокированы все текущие критические IP ({len(items)}):\n\n{preview}\n\nДействие выполнит UFW DENY.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"🚨 Заблокировать все ({len(items)})", callback_data="manual:block_all_critical"), InlineKeyboardButton(text="❌ Отмена", callback_data="manual:cancel")]]))

    @dp.message(F.text == "🔄 Обновить список")
    async def refresh_defense(m, state: FSMContext):
        if not _admin(m): return
        await state.clear(); await m.answer(_defense_text(), reply_markup=defense_menu())

    @dp.callback_query(F.data.startswith("manual:"))
    async def manual_action(callback):
        uid=callback.from_user.id if callback.from_user else 0
        ids={int(v) for v in os.getenv("XFI_GUARD_ADMIN_IDS","").split(",") if v.strip().isdigit()}
        if uid not in ids: await callback.answer("Нет доступа", show_alert=True); return
        parts=callback.data.split(":",2)
        if len(parts)<2: await callback.answer("Некорректное действие", show_alert=True); return
        action=parts[1]
        if action=="cancel":
            await callback.answer("Отменено")
            try: await callback.message.edit_text(_defense_text(), reply_markup=_defense_inline())
            except Exception: pass
            return
        if action=="refresh_menu":
            await callback.answer("Обновлено")
            try: await callback.message.edit_text(_defense_text(), reply_markup=_defense_inline())
            except Exception: pass
            return
        if action=="refresh_threats":
            items=_threat_items()
            await callback.answer("Угрозы обновлены")
            try: await callback.message.edit_text(_threat_text(items), reply_markup=_threat_inline(items))
            except Exception: pass
            return
        if action in {"block_all_critical", "block_all_threats"}:
            key=f"bulk:{action}:{uid}"
            if not _action_once(key):
                await callback.answer("Эта операция уже выполняется", show_alert=True); return
            items=_critical_candidates() if action=="block_all_critical" else _threat_items()
            ok_count=0; failed=[]
            for item in items:
                ip=str(item.get("ip",""))
                try:
                    ok,msg=confirm_block(ip,actor=str(uid),reason="Manual bulk block from threat menu",metadata={"risk_score":item.get("risk_score"),"risk":item.get("risk")})
                    if ok: ok_count += 1
                    else: failed.append(f"{ip}: {msg}")
                except (ValueError,OSError) as exc: failed.append(f"{ip}: {exc}")
            await callback.answer("Готово" if not failed else "Завершено с ошибками", show_alert=True)
            items=_threat_items()
            result=_threat_text(items)+f"\n\nРезультат: заблокировано {ok_count}, ошибок {len(failed)}"
            try: await callback.message.edit_text(result[:3900], reply_markup=_threat_inline(items))
            except Exception: pass
            return
        if len(parts)!=3: await callback.answer("Некорректный IP", show_alert=True); return
        ip=parts[2]
        if not _action_once(f"block:{uid}:{ip}"):
            await callback.answer("Эта операция уже выполняется", show_alert=True); return
        try: ok,message=confirm_block(ip,actor=str(uid),reason="Manual IP block from Telegram")
        except (ValueError,OSError) as exc: ok,message=False,str(exc)
        await callback.answer("Выполнено" if ok else "Ошибка", show_alert=True)
        try:
            items=_threat_items()
            await callback.message.edit_text(("✅ " if ok else "❌ ")+message+"\n\n"+_threat_text(items), reply_markup=_threat_inline(items))
        except Exception: pass

    @dp.message(F.text == "📋 Заблокированные IP")
    async def blocked_list(m):
        if not _admin(m): return
        await m.answer(_defense_text(), reply_markup=defense_menu())

    @dp.message(F.text == "🧮 Рейтинг угроз")
    async def threat_ranking_button(m):
        if not _admin(m): return
        items=_threat_items()
        await m.answer(_threat_text(items), reply_markup=_threat_inline(items))

    @dp.message(Command("threats"))
    async def threats_command(m):
        if not _admin(m): return
        await threat_ranking_button(m)

    @dp.message(F.text == "📜 История защиты")
    async def defense_history_button(m):
        if not _admin(m): return
        items=history(30); text="История защиты пуста." if not items else "\n".join(f"• {x.get('timestamp','')[:19]} | {x.get('action','')} | {x.get('ip','-')} | {x.get('actor','admin')}\n  {x.get('reason','')[:180]}" for x in reversed(items))
        await m.answer("📜 История защиты\n\n"+text[:3800], reply_markup=defense_menu())

    @dp.message(Command("defense_history"))
    async def defense_history_command(m):
        if not _admin(m): return
        await defense_history_button(m)


def _threat_text(items) -> str:
    if not items:
        return "🧮 Рейтинг угроз\n\n✅ Активных угроз не обнаружено."
    lines=["🧮 Рейтинг угроз", "", f"Всего активных угроз: {len(items)}", ""]
    for i,x in enumerate(items[:20],1):
        lines.append(f"{i}. {x.get('ip')} — {str(x.get('risk','unknown')).upper()} {x['risk_score']}/100 | {x.get('events',0)} событий")
    if len(items)>20: lines.append(f"\n… ещё {len(items)-20} угроз")
    return "\n".join(lines)[:3900]
