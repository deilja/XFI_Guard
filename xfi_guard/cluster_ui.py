"""Telegram Cluster Center for XFI Guard."""
from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from aiogram import F
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from .cluster_status import cluster_summary

STATE_PATH = Path(os.getenv("XFI_GUARD_CLUSTER_STATE", "/var/lib/xfi-guard/cluster-state.json"))
DEFAULT_MASTER_URL = "http://127.0.0.1:8765"


def _master_url() -> str:
    return os.getenv("XFI_GUARD_CLUSTER_MASTER_URL", DEFAULT_MASTER_URL).strip().rstrip("/") or DEFAULT_MASTER_URL


def _timeout() -> float:
    try: return max(1.0, min(15.0, float(os.getenv("XFI_GUARD_CLUSTER_TIMEOUT", "5"))))
    except ValueError: return 5.0


def _request(path: str) -> dict:
    url = _master_url() + path
    req = urllib.request.Request(url, method="GET")
    token = os.getenv("XFI_GUARD_CLUSTER_TOKEN", "").strip()
    if not token: raise RuntimeError("XFI_GUARD_CLUSTER_TOKEN не задан")
    req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=_timeout()) as response:
            data = json.loads(response.read().decode())
            if getattr(response, "status", 200) >= 400: raise RuntimeError(data.get("error", "HTTP error"))
            return data
    except urllib.error.HTTPError as exc:
        try: detail = json.loads(exc.read().decode()).get("error", "")
        except Exception: detail = ""
        raise RuntimeError(f"HTTP {exc.code}" + (f": {detail}" if detail else "")) from exc


def _master_diagnostic(exc: Exception) -> str:
    url = _master_url(); parsed = urlsplit(url); host = parsed.hostname or ""; port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if not host: return f"URL: {url}\nDNS/URL: некорректный адрес"
    try:
        with socket.create_connection((host, port), timeout=2): tcp = "🟢 TCP: доступен"
    except socket.gaierror as probe_exc: return f"URL: {url}\n🔴 DNS: {probe_exc}"
    except ConnectionRefusedError: return f"URL: {url}\n🔴 TCP: Connection refused — порт {port} не принимает соединения"
    except TimeoutError: return f"URL: {url}\n🔴 TCP: timeout — узел не отвечает"
    except OSError as probe_exc: return f"URL: {url}\n🔴 TCP: недоступен ({probe_exc})"
    return f"URL: {url}\n{tcp}\n🔴 HTTP: {type(exc).__name__}: {exc}"


def _buttons() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="cluster:refresh")],
        [InlineKeyboardButton(text="🖥 VPS-узлы", callback_data="cluster:nodes")],
        [InlineKeyboardButton(text="🌐 Глобальные блокировки", callback_data="cluster:blocks")],
        [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="cluster:menu")],
    ])


def _state_blocks() -> dict:
    try: return json.loads(STATE_PATH.read_text()).get("blocks", {})
    except (FileNotFoundError, OSError, ValueError): return {}


def _format_nodes(data: dict) -> str:
    nodes = data.get("nodes", [])
    if not nodes: return "• узлы ещё не зарегистрированы"
    summary = cluster_summary(nodes)
    lines = []
    for node in nodes:
        status = node.get("status", "offline"); icon = {"online":"🟢","degraded":"🟡","offline":"🔴"}.get(status,"⚪")
        name = node.get("name") or node.get("hostname") or "-"; reason = node.get("status_reason", "-"); blocked = len(node.get("blocked", []))
        lines += [f"{icon} {name} — {status.upper()}", f"   heartbeat: {reason} | 🔒 {blocked}"]
    counts = summary["counts"]; lines += ["", f"Итого: 🟢 {counts['online']}  🟡 {counts['degraded']}  🔴 {counts['offline']}"]
    return "\n".join(lines)


def _live_blocks() -> list[dict]:
    try: return list(_request("/blocks").get("blocks", []))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, RuntimeError): return [{"ip": ip, **item} for ip, item in _state_blocks().items()]


def cluster_view() -> str:
    try:
        health = _request("/health"); nodes = _request("/nodes"); summary = cluster_summary(nodes.get("nodes", [])); blocks = _live_blocks()
        master_icon = "🟢" if health.get("ok") else "🔴"; cluster_icon = {"online":"🟢","degraded":"🟡","offline":"🔴"}.get(summary["status"],"⚪")
        return ("🌐 XFI GUARD • CLUSTER CENTER\n\n" f"{master_icon} Cluster Master: ONLINE\n" f"{cluster_icon} Cluster: {summary['status'].upper()}\n" f"🔗 {_master_url()}\n\n" f"🖥 Узлы: {summary['total']}\n" f"🟢 Online: {summary['counts']['online']}\n" f"🟡 Degraded: {summary['counts']['degraded']}\n" f"🔴 Offline: {summary['counts']['offline']}\n" f"🚨 Активные угрозы: {int(health.get('threats',0))}\n" f"🔒 Глобальные IP: {len(blocks)}\n\n" "🖥 СОСТОЯНИЕ УЗЛОВ\n" f"{_format_nodes(nodes)}\n\n" "🛡 Политика\n" "• AI consensus → авто-блок\n" "• Fail2Ban → 7 дней\n" "• Global sync → включена\n" "• Heartbeat TTL: 90s")
    except Exception as exc:
        return ("🌐 XFI GUARD • CLUSTER CENTER\n\n🔴 Cluster Master недоступен.\n\n" f"{_master_diagnostic(exc)}\n\nПроверьте:\n• xfi-guard-multi-vps-master.service\n• XFI_GUARD_CLUSTER_MASTER_URL\n• порт Cluster Master\n• XFI_GUARD_CLUSTER_TOKEN")


def blocks_view() -> str:
    blocks = _live_blocks()
    if not blocks: return "🌐 ГЛОБАЛЬНЫЕ БЛОКИРОВКИ\n\nАктивных глобальных блокировок нет."
    lines=["🌐 ГЛОБАЛЬНЫЕ БЛОКИРОВКИ","",f"Всего: {len(blocks)}",""]
    for item in blocks[:40]:
        nodes=item.get("nodes",{}) or {}; applied=sum(1 for state in nodes.values() if state=="blocked"); queued=sum(1 for state in nodes.values() if state=="queued")
        lines += [f"🚫 {item.get('ip','-')}",f"   Источник: {item.get('source_node','-')}",f"   VPS: {applied} применено / {queued} в очереди",f"   До: {item.get('until','-')}"]
    if len(blocks)>40: lines.append(f"… ещё {len(blocks)-40}")
    return "\n".join(lines)[:3900]


def install_cluster_handlers(dp, admin_ids: set[int], main_kb):
    def allowed(message) -> bool: return bool(message.from_user and message.from_user.id in admin_ids)
    @dp.message(F.text.in_({"🌐 Кластер", "🌐 Cluster Center"}))
    async def cluster_button(message):
        if allowed(message): await message.answer(cluster_view(), reply_markup=_buttons())
    @dp.callback_query(F.data == "cluster:refresh")
    async def cluster_refresh(callback):
        if not callback.from_user or callback.from_user.id not in admin_ids: await callback.answer("Нет доступа",show_alert=True); return
        try: await callback.message.edit_text(cluster_view(),reply_markup=_buttons())
        except Exception: pass
        await callback.answer("Кластер обновлён")
    @dp.callback_query(F.data == "cluster:nodes")
    async def cluster_nodes(callback):
        if not callback.from_user or callback.from_user.id not in admin_ids: await callback.answer("Нет доступа",show_alert=True); return
        try: await callback.message.edit_text("🌐 VPS-УЗЛЫ\n\n" + _format_nodes(_request("/nodes")),reply_markup=_buttons())
        except Exception as exc: await callback.message.edit_text("❌ Не удалось получить VPS-узлы.\n\n" + _master_diagnostic(exc),reply_markup=_buttons())
        await callback.answer("VPS-узлы")
    @dp.callback_query(F.data == "cluster:blocks")
    async def cluster_blocks(callback):
        if not callback.from_user or callback.from_user.id not in admin_ids: await callback.answer("Нет доступа",show_alert=True); return
        try: await callback.message.edit_text(blocks_view(),reply_markup=_buttons())
        except Exception: pass
        await callback.answer("Глобальные блокировки")
    @dp.callback_query(F.data == "cluster:menu")
    async def cluster_menu(callback):
        if not callback.from_user or callback.from_user.id not in admin_ids: await callback.answer("Нет доступа",show_alert=True); return
        try: await callback.message.edit_text("🏠 Главное меню\n\nВыберите раздел в нижнем меню.")
        except Exception: pass
        await callback.answer()
