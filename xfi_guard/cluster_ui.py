"""Telegram Cluster Center for XFI Guard."""
from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request
from pathlib import Path

from aiogram import F
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .cluster_status import cluster_summary

STATE_PATH = Path(os.getenv("XFI_GUARD_CLUSTER_STATE", "/var/lib/xfi-guard/cluster-state.json"))
DEFAULT_MASTER_URL = "http://127.0.0.1:8765"


def _master_url() -> str:
    return os.getenv("XFI_GUARD_CLUSTER_MASTER_URL", DEFAULT_MASTER_URL).strip().rstrip("/") or DEFAULT_MASTER_URL


def _timeout() -> float:
    try:
        return max(1.0, min(15.0, float(os.getenv("XFI_GUARD_CLUSTER_TIMEOUT", "5"))))
    except ValueError:
        return 5.0


def _get(path: str) -> dict:
    req = urllib.request.Request(_master_url() + path, method="GET")
    token = os.getenv("XFI_GUARD_CLUSTER_TOKEN", "").strip()
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=_timeout()) as response:
        return json.loads(response.read().decode())


def _master_diagnostic(exc: Exception) -> str:
    url = _master_url()
    try:
        from urllib.parse import urlsplit
        parsed = urlsplit(url)
        host = parsed.hostname or ""
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        with socket.create_connection((host, port), timeout=2):
            tcp = "TCP: доступен"
        return f"URL: {url}\n{tcp}, HTTP: {type(exc).__name__}: {exc}"
    except Exception as probe_exc:
        return f"URL: {url}\nTCP: недоступен ({type(probe_exc).__name__}: {probe_exc})"


def _buttons() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="cluster:refresh")],
        [InlineKeyboardButton(text="🌐 Глобальные блокировки", callback_data="cluster:blocks")],
    ])


def _state_blocks() -> dict:
    try:
        return json.loads(STATE_PATH.read_text()).get("blocks", {})
    except (FileNotFoundError, OSError, ValueError):
        return {}


def _format_nodes(data: dict) -> str:
    nodes = data.get("nodes", [])
    if not nodes:
        return "• узлы ещё не зарегистрированы"
    summary = cluster_summary(nodes)
    lines = []
    for node in nodes:
        status = node.get("status", "offline")
        icon = {"online": "🟢", "degraded": "🟡", "offline": "🔴"}.get(status, "⚪")
        name = node.get("name") or node.get("hostname") or "-"
        reason = node.get("status_reason", "-")
        blocked = len(node.get("blocked", []))
        lines.append(f"{icon} {name} — {status.upper()}")
        lines.append(f"   heartbeat: {reason} | 🔒 {blocked}")
    counts = summary["counts"]
    lines.append("")
    lines.append(f"Итого: 🟢 {counts['online']}  🟡 {counts['degraded']}  🔴 {counts['offline']}")
    return "\n".join(lines)


def _live_blocks() -> list[dict]:
    try:
        return list(_get("/blocks").get("blocks", []))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return [{"ip": ip, **item} for ip, item in _state_blocks().items()]


def cluster_view() -> str:
    try:
        health = _get("/health")
        nodes = _get("/nodes")
        node_items = nodes.get("nodes", [])
        summary = cluster_summary(node_items)
        blocks = _live_blocks()
        master_icon = "🟢" if health.get("ok") else "🔴"
        cluster_icon = {"online": "🟢", "degraded": "🟡", "offline": "🔴"}.get(summary["status"], "⚪")
        return (
            "🌐 XFI GUARD • CLUSTER CENTER\n\n"
            f"{master_icon} Cluster Master: ONLINE\n"
            f"{cluster_icon} Cluster: {summary['status'].upper()}\n"
            f"🔗 {_master_url()}\n\n"
            f"🖥 Узлы: {summary['total']}\n"
            f"🟢 Online: {summary['counts']['online']}\n"
            f"🟡 Degraded: {summary['counts']['degraded']}\n"
            f"🔴 Offline: {summary['counts']['offline']}\n"
            f"🚨 Активные угрозы: {int(health.get('threats', 0))}\n"
            f"🔒 Глобальные IP: {len(blocks)}\n\n"
            "🖥 СОСТОЯНИЕ УЗЛОВ\n"
            f"{_format_nodes(nodes)}\n\n"
            "🛡 Политика\n"
            "• AI high-confidence → авто-блок\n"
            "• Fail2Ban → 7 дней\n"
            "• Global sync → включена\n"
            "• Heartbeat TTL: 90s"
        )
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        return (
            "🌐 XFI GUARD • CLUSTER CENTER\n\n"
            "🔴 Cluster Master недоступен.\n\n"
            f"{_master_diagnostic(exc)}\n\n"
            "Проверьте:\n"
            "• xfi-guard-multi-vps-master.service\n"
            "• XFI_GUARD_CLUSTER_MASTER_URL\n"
            "• порт 8765\n"
            "• XFI_GUARD_CLUSTER_TOKEN"
        )


def blocks_view() -> str:
    blocks = _live_blocks()
    if not blocks:
        return "🌐 ГЛОБАЛЬНЫЕ БЛОКИРОВКИ\n\nАктивных глобальных блокировок нет."
    lines = ["🌐 ГЛОБАЛЬНЫЕ БЛОКИРОВКИ", "", f"Всего: {len(blocks)}", ""]
    for item in blocks[:40]:
        nodes = item.get("nodes", {}) or {}
        applied = sum(1 for state in nodes.values() if state == "blocked")
        queued = sum(1 for state in nodes.values() if state == "queued")
        lines += [
            f"🚫 {item.get('ip', '-')}",
            f"   Источник: {item.get('source_node', '-')}",
            f"   VPS: {applied} применено / {queued} в очереди",
            f"   До: {item.get('until', '-')}",
        ]
    if len(blocks) > 40:
        lines.append(f"… ещё {len(blocks)-40}")
    return "\n".join(lines)[:3900]


def install_cluster_handlers(dp, admin_ids: set[int], main_kb):
    def allowed(message) -> bool:
        return bool(message.from_user and message.from_user.id in admin_ids)

    @dp.message(F.text == "🌐 Cluster Center")
    async def cluster_button(message):
        if allowed(message):
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
