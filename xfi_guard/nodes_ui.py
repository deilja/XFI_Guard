"""Telegram FSM for managing VPS nodes and bootstrapping XFI Guard."""
from __future__ import annotations

import asyncio
from aiogram import F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from .nodes import collect_nodes
from .nodes_manager import add_node, list_configured_nodes, remove_node
from .node_bootstrap import bootstrap


class NodeForm(StatesGroup):
    name = State()
    host = State()
    user = State()
    port = State()


def _menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Добавить VPS"), KeyboardButton(text="🗑 Удалить VPS")],
            [KeyboardButton(text="🔌 Подключить XFI Guard")],
            [KeyboardButton(text="🔄 Проверить VPS"), KeyboardButton(text="⬅️ Главное меню")],
        ], resize_keyboard=True, is_persistent=True,
    )


def install_node_handlers(dp, admin_ids: set[int]):
    def is_admin(message) -> bool:
        return bool(message.from_user and message.from_user.id in admin_ids)

    @dp.message(F.text == "🖥 VPS узлы")
    async def nodes_menu(message, state: FSMContext):
        if not is_admin(message): return
        await state.clear()
        configured = list_configured_nodes()
        rows = ["🖥 VPS УЗЛЫ", "", f"Настроено: {len(configured)}"]
        for n in configured:
            rows.append(f"• {n.get('name')} — {n.get('user','root')}@{n.get('host')}:{n.get('port',22)}")
        if not configured: rows.append("• узлов пока нет")
        rows += ["", "SSH: Agent/known_hosts", "Пароли и приватные ключи не сохраняются."]
        await message.answer("\n".join(rows), reply_markup=_menu())

    @dp.message(F.text == "➕ Добавить VPS")
    async def add_start(message, state: FSMContext):
        if not is_admin(message): return
        await state.clear(); await state.set_state(NodeForm.name)
        await message.answer("➕ Добавление VPS\n\nВведите имя узла, например: vps-de\n\nДля отмены нажмите «⬅️ Главное меню».")

    @dp.message(F.text == "🗑 Удалить VPS")
    async def remove_start(message, state: FSMContext):
        if not is_admin(message): return
        names = [str(x.get("name")) for x in list_configured_nodes()]
        if not names:
            await message.answer("Нет настроенных VPS.", reply_markup=_menu()); return
        await state.clear(); await state.update_data(remove_mode=True); await state.set_state(NodeForm.name)
        await message.answer("🗑 Введите имя VPS для удаления:\n\n" + "\n".join(f"• {x}" for x in names) + "\n\nДля отмены нажмите «⬅️ Главное меню».")

    @dp.message(F.text == "🔌 Подключить XFI Guard")
    async def bootstrap_menu(message):
        if not is_admin(message): return
        nodes = list_configured_nodes()
        if not nodes:
            await message.answer("Нет настроенных VPS. Сначала используйте «➕ Добавить VPS».", reply_markup=_menu()); return
        await message.answer("⏳ Подключаю XFI Guard на всех настроенных VPS через SSH Agent...\n\nПароли и ключи не передаются.")
        for node in nodes:
            name, host = node.get("name", "-"), node.get("host", "")
            user = node.get("user", "root")
            try:
                port = int(node.get("port", 22))
            except (TypeError, ValueError):
                await message.answer(f"🔴 {name}\n\nНекорректный SSH порт в конфигурации.")
                continue
            ok, output = await asyncio.to_thread(bootstrap, host, user, port)
            if ok:
                await message.answer(f"🟢 {name}\n\nXFI Guard подключён/обновлён.\nFail2Ban: проверен.\n\n{output[-1200:]}")
            else:
                await message.answer(f"🔴 {name}\n\nПодключение не выполнено.\n\n{output[-1800:]}")

    # Must be available while any NodeForm state is active. Previously the
    # state handlers consumed this button as ordinary input and port parsing
    # attempted int("⬅️ Главное меню").
    @dp.message(F.text == "⬅️ Главное меню")
    async def cancel_node_form(message, state: FSMContext):
        if not is_admin(message): return
        await state.clear()
        await message.answer("🏠 Главное меню", reply_markup=_menu())

    @dp.message(NodeForm.name)
    async def node_name(message, state: FSMContext):
        if not is_admin(message): return
        text = (message.text or "").strip()
        if not text:
            await message.answer("❌ Имя узла не может быть пустым. Введите имя ещё раз:")
            return
        data = await state.get_data()
        if data.get("remove_mode"):
            try:
                await asyncio.to_thread(remove_node, text)
                await state.clear(); await message.answer("✅ VPS удалён из конфигурации.", reply_markup=_menu())
            except Exception as exc:
                await state.clear(); await message.answer(f"❌ Не удалось удалить VPS: {type(exc).__name__}: {exc}", reply_markup=_menu())
            return
        await state.update_data(name=text); await state.set_state(NodeForm.host)
        await message.answer("Введите IP-адрес или DNS имя VPS:\n\nДля отмены нажмите «⬅️ Главное меню».")

    @dp.message(NodeForm.host)
    async def node_host(message, state: FSMContext):
        if not is_admin(message): return
        text = (message.text or "").strip()
        if not text or any(c in text for c in " /\\\t\r\n"):
            await message.answer("❌ Некорректный IP/DNS. Введите IP-адрес или DNS имя ещё раз:")
            return
        await state.update_data(host=text); await state.set_state(NodeForm.user)
        await message.answer("Введите SSH пользователя (по умолчанию root):\n\nДля отмены нажмите «⬅️ Главное меню».")

    @dp.message(NodeForm.user)
    async def node_user(message, state: FSMContext):
        if not is_admin(message): return
        text = (message.text or "").strip()
        if text and any(c.isspace() for c in text):
            await message.answer("❌ Некорректный SSH пользователь. Введите ещё раз:")
            return
        await state.update_data(user=text or "root"); await state.set_state(NodeForm.port)
        await message.answer("Введите SSH порт (по умолчанию 22):\n\nДля отмены нажмите «⬅️ Главное меню».")

    @dp.message(NodeForm.port)
    async def node_port(message, state: FSMContext):
        if not is_admin(message): return
        text = (message.text or "").strip()
        if not text:
            port = 22
        else:
            try:
                port = int(text)
            except ValueError:
                await message.answer("❌ SSH порт должен быть числом 1..65535. Введите ещё раз:")
                return
        if not 1 <= port <= 65535:
            await message.answer("❌ SSH порт должен быть в диапазоне 1..65535. Введите ещё раз:")
            return
        data = await state.get_data()
        try:
            await asyncio.to_thread(add_node, data["name"], data["host"], data.get("user", "root"), port)
            await state.clear()
            await message.answer(f"✅ VPS добавлен\n\n{data['name']} — {data['user']}@{data['host']}:{port}\n\nИспользуйте «🔌 Подключить XFI Guard» для настройки узла.", reply_markup=_menu())
            nodes = await asyncio.to_thread(collect_nodes)
            current = next((x for x in nodes if x.get("name") == data["name"]), None)
            if current and current.get("status") == "online":
                await message.answer(f"🟢 SSH: OK\nXFI Guard: {current.get('xfi_guard','—')}\nFail2Ban: {current.get('fail2ban','—')}")
            else:
                err = current.get("error", "SSH недоступен") if current else "узел не найден"
                await message.answer(f"🟡 Узел сохранён, но проверка не прошла:\n{err}")
        except Exception as exc:
            await state.clear(); await message.answer(f"❌ VPS не добавлен: {type(exc).__name__}: {exc}", reply_markup=_menu())

    @dp.message(F.text == "🔄 Проверить VPS")
    async def probe_all(message):
        if not is_admin(message): return
        nodes = await asyncio.to_thread(collect_nodes)
        if not nodes:
            await message.answer("VPS узлы не настроены.", reply_markup=_menu()); return
        lines = ["🖥 Проверка VPS", ""]
        for x in nodes:
            icon = "🟢" if x.get("status") == "online" else "🔴"
            lines.append(f"{icon} {x.get('name')} — {x.get('host')}")
            lines.append(f"   XFI Guard: {x.get('xfi_guard','—')}; Fail2Ban: {x.get('fail2ban','—')}")
            if x.get("error"): lines.append(f"   {x['error']}")
        await message.answer("\n".join(lines)[:3900], reply_markup=_menu())
