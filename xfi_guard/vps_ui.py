"""Compact Telegram UI for VPS diagnostics and multi-node monitoring."""
from __future__ import annotations

import asyncio
import os
import shutil
import socket
import subprocess
import ipaddress
import time

from aiogram import Dispatcher, F
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from .nodes import collect_nodes, load_nodes, probe_node


def _admin(message) -> bool:
    ids = {int(v) for v in os.getenv("XFI_GUARD_ADMIN_IDS", "").split(",") if v.strip().isdigit()}
    return bool(message.from_user and message.from_user.id in ids)


def _kb(rows):
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=x) for x in row] for row in rows], resize_keyboard=True, is_persistent=True)


def vps_menu():
    return _kb([
        ["📊 Статус VPS"], ["🧠 Ресурсы", "🌐 Сеть"],
        ["🛡 Безопасность", "🚫 Блокировки"], ["📋 Логи", "🔄 Проверить"],
        ["🖥 Узлы VPS"], ["⬅️ Главное меню"],
    ])


def _node_buttons(nodes):
    rows = []
    for i, node in enumerate(nodes[:20]):
        rows.append([InlineKeyboardButton(text=f"🔎 {node.name}", callback_data=f"vps:node:{i}")])
    rows.append([InlineKeyboardButton(text="🔄 Обновить узлы", callback_data="vps:nodes:refresh")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _read(path, default="—"):
    try:
        with open(path, encoding="utf-8") as f: return f.read().strip() or default
    except Exception: return default


def _mem():
    data = {}
    for line in _read("/proc/meminfo", "").splitlines():
        parts = line.split()
        if len(parts) >= 2: data[parts[0].rstrip(":")] = int(parts[1])
    total, available = data.get("MemTotal", 0), data.get("MemAvailable", data.get("MemFree", 0))
    used = max(0, total - available)
    return used / total * 100 if total else 0, used / 1024 / 1024, total / 1024 / 1024


def _disk():
    total, used, _ = shutil.disk_usage("/")
    return used / total * 100 if total else 0, used / 1024**3, total / 1024**3


def _load():
    try:
        a, b, c = os.getloadavg(); return f"{a:.2f} / {b:.2f} / {c:.2f}"
    except OSError: return "—"


def _uptime():
    try: seconds = int(float(_read("/proc/uptime", "0").split()[0]))
    except (ValueError, IndexError): return "—"
    days, seconds = divmod(seconds, 86400); hours, seconds = divmod(seconds, 3600); minutes = seconds // 60
    return f"{days}д {hours}ч {minutes}м"


def _cpu():
    try:
        p = subprocess.run(["top", "-bn1"], capture_output=True, text=True, timeout=3, check=False)
        import re
        for line in p.stdout.splitlines():
            if "Cpu(s)" in line or "%Cpu(s)" in line:
                idle = re.search(r"([\d.,]+)\s*id", line)
                if idle: return max(0.0, 100.0 - float(idle.group(1).replace(",", ".")))
    except Exception: pass
    return 0.0


def status_text():
    mem_used, mem_used_gb, mem_total_gb = _mem(); disk_used, disk_used_gb, disk_total_gb = _disk()
    return "\n".join(["📊 СТАТУС VPS", "", f"Hostname: {socket.gethostname()}", f"Uptime: {_uptime()}", f"CPU: {_cpu():.1f}%", f"RAM: {mem_used:.1f}% ({mem_used_gb:.1f}/{mem_total_gb:.1f} GB)", f"Disk /: {disk_used:.1f}% ({disk_used_gb:.1f}/{disk_total_gb:.1f} GB)", f"Load: {_load()}"])


def network_text():
    try:
        p = subprocess.run(["ip", "-brief", "addr"], capture_output=True, text=True, timeout=3, check=False)
        routes = subprocess.run(["ip", "route", "show", "default"], capture_output=True, text=True, timeout=3, check=False)
        return "🌐 СЕТЬ\n\n" + (p.stdout.strip() or "Интерфейсы не получены")[:2400] + "\n\nDefault route:\n" + (routes.stdout.strip() or "нет")
    except Exception as exc: return f"❌ Сеть: {type(exc).__name__}: {exc}"


def security_text():
    def active(service):
        try: return subprocess.run(["systemctl", "is-active", service], capture_output=True, text=True, timeout=3, check=False).stdout.strip() or "unknown"
        except Exception: return "unknown"
    return "\n".join(["🛡 БЕЗОПАСНОСТЬ VPS", "", f"XFI Guard: {active('xfi-guard')}", f"Fail2Ban: {active('fail2ban')}", f"UFW: {active('ufw')}", f"SSH: {active('ssh')}"])


def logs_text():
    try:
        p = subprocess.run(["journalctl", "-u", "xfi-guard", "-u", "xfi-guard-bot", "-u", "fail2ban", "-n", "30", "--no-pager"], capture_output=True, text=True, timeout=6, check=False)
        return "📋 ПОСЛЕДНИЕ ЛОГИ\n\n" + (p.stdout or p.stderr or "Событий нет.")[-3400:]
    except Exception as exc: return f"❌ Логи: {type(exc).__name__}: {exc}"


def _nodes_text(items):
    if not items: return "🖥 VPS УЗЛЫ\n\nПодключённые узлы не настроены."
    online = sum(x.get("status") == "online" for x in items); degraded = sum(x.get("status") == "degraded" for x in items); offline = len(items) - online - degraded
    lines = ["🖥 VPS УЗЛЫ", "", f"Всего: {len(items)} | 🟢 {online} | 🟡 {degraded} | 🔴 {offline}", ""]
    for x in items:
        icon = {"online": "🟢", "degraded": "🟡", "offline": "🔴"}.get(x.get("status"), "⚪")
        lines += [f"{icon} {x.get('name', 'unknown')} — {x.get('host', '—')}", f"   Guard: {x.get('xfi_guard', '—')} | Fail2Ban: {x.get('fail2ban', '—')}"]
        if x.get("error"): lines.append(f"   Ошибка: {x['error'][:260]}")
    return "\n".join(lines)[:3900]


def _node_detail(items, index):
    if index < 0 or index >= len(items): return "❌ Узел не найден."
    x = items[index]; icon = "🟢" if x.get("status") == "online" else "🔴"
    return "\n".join([f"{icon} VPS: {x.get('name', 'unknown')}", "", f"Host: {x.get('host', '—')}", f"Status: {x.get('status', 'offline').upper()}", f"Hostname: {x.get('hostname', '—')}", f"XFI Guard: {x.get('xfi_guard', '—')}", f"Fail2Ban: {x.get('fail2ban', '—')}", f"Проверено: {time.strftime('%Y-%m-%d %H:%M:%S')}", f"Ошибка: {x.get('error', 'нет')}"])


def install_vps_handlers(dp: Dispatcher, main_kb) -> None:
    if getattr(dp, "_xfi_vps_handlers_installed", False): return
    dp._xfi_vps_handlers_installed = True

    @dp.message(F.text == "🖥 VPS")
    async def vps(message):
        if _admin(message): await message.answer("🖥 VPS\n\nЦентр диагностики и управления VPS.", reply_markup=vps_menu())

    @dp.message(F.text == "📊 Статус VPS")
    async def status(message):
        if _admin(message): await message.answer(status_text(), reply_markup=vps_menu())

    @dp.message(F.text == "🧠 Ресурсы")
    async def resources(message):
        if _admin(message): await message.answer(status_text().replace("📊 СТАТУС VPS", "🧠 РЕСУРСЫ VPS"), reply_markup=vps_menu())

    @dp.message(F.text == "🌐 Сеть")
    async def network(message):
        if _admin(message): await message.answer(network_text(), reply_markup=vps_menu())

    @dp.message(F.text == "🛡 Безопасность")
    async def security(message):
        if _admin(message): await message.answer(security_text(), reply_markup=vps_menu())

    @dp.message(F.text == "📋 Логи")
    async def logs(message):
        if _admin(message): await message.answer(logs_text(), reply_markup=vps_menu())

    @dp.message(F.text == "🔄 Проверить")
    async def check(message):
        if _admin(message):
            await message.answer("⏳ Проверяю VPS...", reply_markup=vps_menu())
            await message.answer(status_text() + "\n\n" + security_text(), reply_markup=vps_menu())

    @dp.message(F.text == "🖥 Узлы VPS")
    async def nodes(message):
        if not _admin(message): return
        try:
            configured = load_nodes(); items = await asyncio.to_thread(collect_nodes)
            await message.answer(_nodes_text(items), reply_markup=_node_buttons(configured))
        except Exception as exc: await message.answer(f"❌ Узлы VPS: {type(exc).__name__}: {exc}", reply_markup=vps_menu())

    @dp.callback_query(F.data == "vps:nodes:refresh")
    async def nodes_refresh(callback):
        if not callback.from_user or callback.from_user.id not in {int(v) for v in os.getenv("XFI_GUARD_ADMIN_IDS", "").split(",") if v.strip().isdigit()}:
            await callback.answer("Нет доступа", show_alert=True); return
        items = await asyncio.to_thread(collect_nodes); configured = load_nodes()
        try: await callback.message.edit_text(_nodes_text(items), reply_markup=_node_buttons(configured))
        except Exception: pass
        await callback.answer("Узлы обновлены")

    @dp.callback_query(F.data.startswith("vps:node:"))
    async def node_detail(callback):
        if not callback.from_user or callback.from_user.id not in {int(v) for v in os.getenv("XFI_GUARD_ADMIN_IDS", "").split(",") if v.strip().isdigit()}:
            await callback.answer("Нет доступа", show_alert=True); return
        try: index = int(callback.data.rsplit(":", 1)[1]); configured = load_nodes()
        except ValueError: await callback.answer("Некорректный узел", show_alert=True); return
        if index >= len(configured): await callback.answer("Узел не найден", show_alert=True); return
        item = await asyncio.to_thread(probe_node, configured[index]);
        markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔄 Проверить узел", callback_data=f"vps:node:{index}")], [InlineKeyboardButton(text="⬅️ Все узлы", callback_data="vps:nodes:refresh")]])
        try: await callback.message.edit_text(_node_detail([item], 0), reply_markup=markup)
        except Exception: pass
        await callback.answer()

    @dp.message(F.text == "🚫 Блокировки")
    async def blocks(message):
        if _admin(message):
            from .bot import blocked_view
            await message.answer(blocked_view(), reply_markup=vps_menu())
