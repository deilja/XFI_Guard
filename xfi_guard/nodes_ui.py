"""Telegram FSM for adding/removing VPS nodes from the admin panel."""
from __future__ import annotations

import asyncio
from aiogram import F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from .nodes import collect_nodes
from .nodes_manager import add_node, list_configured_nodes, remove_node


class NodeForm(StatesGroup):
    name = State()
    host = State()
    user = State()
    port = State()


def _menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Добавить VPS"), KeyboardButton(text="🗑 Удалить VPS")],
            [KeyboardButton(text="🔄 Проверить VPS"), KeyboardButton(text="⬅️ Главное меню")],
        ], resize_keyboard=True, is_persistent=True,
    )


def install_node_handlers(dp, admin_ids: set[int]):
    def is_admin(message) -> bool:
        return bool(message.from_user and message.from_user.id in admin_ids)

    @dp.message(F.text == "🖥 VPS узлы")
    async def nodes_menu(message, state: FSMContext):
        if not is_admin(message):
            return
        await state.clear()
        configured = list_configured_nodes()
        rows = ["🖥 VPS УЗЛЫ", "", f"Настроено: {len(configured)}"]
        for n in configured:
            rows.append(f"• {n.get('name')} — {n.get('user','root')}@{n.get('host')}:{n.get('port',22)}")
        if not configured:
            rows.append("• узлов пока нет")
        rows += ["", "Добавление выполняется через SSH Agent/known_hosts.", "Пароли и приватные ключи не сохраняются."]
        await message.answer("\n".join(rows), reply_markup=_menu())

    @dp.message(F.text == "➕ Добавить VPS")
    async def add_start(message, state: FSMContext):
        if not is_admin(message): return
        await state.set_state(NodeForm.name)
        await message.answer("➕ Добавление VPS\n\nВведите имя узла, например: vps-de")

    @dp.message(NodeForm.name)
    async def add_name(message, state: FSMContext):
        if not is_admin(message): return
        await state.update_data(name=message.text.strip())
        await state.set_state(NodeForm.host)
        await message.answer("Введите IP-адрес или DNS имя VPS:")

    @dp.message(NodeForm.host)
    async def add_host(message, state: FSMContext):
        if not is_admin(message): return
        await state.update_data(host=message.text.strip())
        await state.set_state(NodeForm.user)
        await message.answer("Введите SSH пользователя (по умолчанию root):")

    @dp.message(NodeForm.user)
    async def add_user(message, state: FSMContext):
        if not is_admin(message): return
        await state.update_data(user=message.text.strip() or "root")
        await state.set_state(NodeForm.port)
        await message.answer("Введите SSH порт (по умолчанию 22):")

    @dp.message(NodeForm.port)
    async def add_port(message, state: FSMContext):
        if not is_admin(message): return
        try:
            port = int(message.text.strip() or "22")
            data = await state.get_data()
            await asyncio.to_thread(add_node, data["name"], data["host"], data.get("user", "root"), port)
            await state.clear()
            await message.answer(
                f"✅ VPS добавлен\n\n{data['name']} — {data['user']}@{data['host']}:{port}\n\n"
                "Проверяю SSH и XFI Guard...",
                reply_markup=_menu(),
            )
            nodes = await asyncio.to_thread(collect_nodes)
            current = next((x for x in nodes if x.get("name") == data["name"]), None)
            if current and current.get("status") == "online":
                await message.answer(f"🟢 SSH: OK\nXFI Guard: {current.get('xfi_guard','—')}\nFail2Ban: {current.get('fail2ban','—')}")
            else:
                err = current.get("error", "SSH недоступен") if current else "узел не найден"
                await message.answer(f"🟡 Узел сохранён, но проверка не прошла:\n{err}")
        except Exception as exc:
            await state.clear()
            await message.answer(f"❌ VPS не добавлен: {type(exc).__name__}: {exc}", reply_markup=_menu())

    @dp.message(F.text == "🗑 Удалить VPS")
    async def remove_start(message, state: FSMContext):
        if not is_admin(message): return
        names = [str(x.get("name")) for x in list_configured_nodes()]
        if not names:
            await message.answer("Нет настроенных VPS.", reply_markup=_menu())
            return
        await state.update_data(remove_mode=True)
        await state.set_state(NodeForm.name)
        await message.answer("🗑 Введите имя VPS для удаления:\n\n" + "\n".join(f"• {x}" for x in names))

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

    @dp.message(NodeForm.name)
    async def remove_or_add_name(message, state: FSMContext):
        if not is_admin(message): return
        data = await state.get_data()
        if data.get("remove_mode"):
            try:
                await asyncio.to_thread(remove_node, message.text.strip())
                await state.clear()
                await message.answer("✅ VPS удалён из конфигурации.", reply_markup=_menu())
            except Exception as exc:
                await state.clear()
                await message.answer(f"❌ Не удалось удалить VPS: {exc}", reply_markup=_menu())
