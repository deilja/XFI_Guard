"""Telegram Cluster Center for XFI Guard."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from aiogram import F
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

STATE_PATH = Path(os.getenv("XFI_GUARD_CLUSTER_STATE", "/var/lib/xfi-guard/cluster-state.json"))


def _master_url() -> str:
    return os.getenv("XFI_GUARD_CLUSTER_MASTER_URL", "http://127.0.0.1:8765").rstrip("/")


def _get(path: str) -> dict:
    req = urllib.request.Request(_master_url() + path, method="GET")
    token = os.getenv("XFI_GUARD_CLUSTER_TOKEN", "").strip()
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=5) as response:
        return json.loads(response.read().decode())


def _buttons() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="cluster:refresh")],
        [InlineKeyboardButton(text="🌐 Глобальные блокировки", callback_data="cluster:blocks")],
    ])


def _state_blocks() -> dict:
    try:
        data = json.loads(STATE_PATH.read_text())
        return data.get("blocks", {})
    except (FileNotFoundError, OSError, ValueError):
        return {}


def _format_nodes(data: dict) -> str:
    nodes = data.get("nodes", [])
    if not nodes:
        return "• узлы ещё не зарегистрированы"
    lines = []
    for node in nodes:
        icon = "🟢" if node.get("online") else "🔴"
        age = node.get("last_seen", 0)
        lines.append(f"{icon} {node.get('name', '-')} — {'ONLINE' if node.get('online') else 'OFFLINE'}")
        blocked = node.get("blocked", [])
        lines.append(f"   🔒 Блокировок: {len(blocked)}")
    return "\n".join(lines)


def cluster_view() -> str:
    try:
        health = _get("/health")
        nodes = _get("/nodes")
        total = int(health.get("nodes", 0))
        online = int(health.get("online", 0))
        threats = int(health.get("threats", 0))
        blocks = _state_blocks()
        return (
            "🌐 XFI GUARD • CLUSTER CENTER\n\n"
            f"🖥 Узлы: {online}/{total} онлайн\n"
            f"🚨 Активные угрозы: {threats}\n"
            f"🔒 Глобальные IP: {len(blocks)}\n"
            "⏱ Срок автоблокировки: 7 дней\n\n"
            "🖥 СОСТОЯНИЕ УЗЛОВ\n"
            f"{_format_nodes(nodes)}\n\n"
            "🛡 Политика\n"
            "• AI high-confidence → авто-блок\n"
            "• Fail2Ban → 7 дней\n"
            "• Global sync → включена\n"
            "• Пароли VPS → не хранятся"
        )
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        return (
            "🌐 XFI GUARD • CLUSTER CENTER\n\n"
            "🔴 Cluster Master недоступен.\n\n"
            f"Причина: {type(exc).__name__}: {exc}\n\n"
            "Проверьте cluster master и XFI_GUARD_CLUSTER_MASTER_URL."
        )


def blocks_view() -> str:
    blocks = _state_blocks()
    if not blocks:
        return "🌐 ГЛОБАЛЬНЫЕ БЛОКИРОВКИ\n\nАктивных глобальных блокировок нет."
    lines = ["🌐 ГЛОБАЛЬНЫЕ БЛОКИРОВКИ", "", f"Всего: {len(blocks)}", ""]
    for ip, item in list(blocks.items())[:40]:
        nodes = item.get("nodes", {})
        applied = sum(1 for state in nodes.values() if state == "blocked")
        queued = sum(1 for state in nodes.values() if state == "queued")
        lines.append(f"🚫 {ip}")
        lines.append(f"   VPS: {applied} ✅ / {queued} ⏳")
        lines.append(f"   До: {item.get('until', '-')}")
    if len(blocks) > 40:
        lines.append(f"… ещё {len(blocks)-40}")
    return "\n".join(lines)[:3900]


def install_cluster_handlers(dp, admin_ids: set[int], main_kb):
    def allowed(message) -> bool:
        return bool(message.from_user and message.from_user.id in admin_ids)

    @dp.message(F.text == "🌐 Cluster Center")
    async def cluster_button(message):
        if not allowed(message):
            return
        await message.answer(cluster_view(), reply_markup=_buttons())

    @dp.callback_query(F.data == "cluster:refresh")
    async def cluster_refresh(callback):
        if not callback.from_user or callback.from_user.id not in admin_ids:
            await callback.answer("Нет доступа", show_alert=True)
            return
        try:
            await callback.message.edit_text(cluster_view(), reply_markup=_buttons())
        except Exception:
            pass
        await callback.answer("Кластер обновлён")

    @dp.callback_query(F.data == "cluster:blocks")
    async def cluster_blocks(callback):
        if not callback.from_user or callback.from_user.id not in admin_ids:
            await callback.answer("Нет доступа", show_alert=True)
            return
        try:
            await callback.message.edit_text(blocks_view(), reply_markup=_buttons())
        except Exception:
            pass
        await callback.answer("Глобальные блокировки")
