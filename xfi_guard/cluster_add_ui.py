"""Telegram UI for securely enrolling remote VPS nodes into XFI Guard cluster."""
from __future__ import annotations

import asyncio
import os

from aiogram import F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, CallbackQuery

from .admin_auth import authorized
from .cluster_ui import _validate_master_url
from .node_bootstrap import bootstrap


class AddVPSStates(StatesGroup):
    host = State()
    port = State()
    user = State()
    confirm = State()


def _confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Установить и подключить", callback_data="cluster:add:install")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cluster:add:cancel")],
    ])


def _master_url() -> str:
    return os.getenv("XFI_GUARD_CLUSTER_MASTER_URL", "").strip().rstrip("/")


def _credentials_ready() -> bool:
    return bool(os.getenv("XFI_GUARD_CLUSTER_TOKEN", "").strip() and os.getenv("XFI_GUARD_CLUSTER_SECRET", "").strip())


def install_cluster_add_handlers(dp) -> None:
    @dp.callback_query(F.data == "cluster:add")
    async def add_start(c: CallbackQuery, state: FSMContext):
        if not authorized(c):
            return await c.answer("Нет доступа", show_alert=True)
        if not _credentials_ready():
            return await c.answer("Cluster credentials не настроены", show_alert=True)
        master = _master_url()
        if not master:
            return await c.answer("XFI_GUARD_CLUSTER_MASTER_URL не задан", show_alert=True)
        try:
            _validate_master_url(master)
        except RuntimeError as exc:
            return await c.answer(str(exc), show_alert=True)
        await state.clear()
        await state.set_state(AddVPSStates.host)
        await c.message.answer(
            "➕ ДОБАВЛЕНИЕ VPS\n\n"
            "Введите IP-адрес или hostname нового VPS.\n\n"
            "SSH должен быть доступен с Cluster Master, а ключ — уже находиться в SSH agent/known_hosts."
        )
        await c.answer()

    @dp.message(AddVPSStates.host)
    async def add_host(message: Message, state: FSMContext):
        if not authorized(message):
            return
        host = (message.text or "").strip()
        if not host or any(ch.isspace() for ch in host) or len(host) > 255:
            return await message.answer("❌ Некорректный IP/hostname. Повторите ввод.")
        await state.update_data(host=host)
        await state.set_state(AddVPSStates.port)
        await message.answer("Введите SSH-порт VPS (по умолчанию 22):")

    @dp.message(AddVPSStates.port)
    async def add_port(message: Message, state: FSMContext):
        if not authorized(message):
            return
        raw = (message.text or "").strip()
        if not raw:
            port = 22
        else:
            try:
                port = int(raw)
            except ValueError:
                port = 0
        if not 1 <= port <= 65535:
            return await message.answer("❌ Порт должен быть числом от 1 до 65535.")
        await state.update_data(port=port)
        await state.set_state(AddVPSStates.user)
        await message.answer("Введите SSH-пользователя (по умолчанию root):")

    @dp.message(AddVPSStates.user)
    async def add_user(message: Message, state: FSMContext):
        if not authorized(message):
            return
        user = (message.text or "").strip() or "root"
        if any(ch.isspace() for ch in user) or len(user) > 64:
            return await message.answer("❌ Некорректное имя SSH-пользователя.")
        data = await state.update_data(user=user)
        await state.set_state(AddVPSStates.confirm)
        await message.answer(
            "🧩 ПОДКЛЮЧЕНИЕ VPS\n\n"
            f"Host: {data['host']}\n"
            f"SSH: {user}@{data['host']}:{data['port']}\n"
            f"Cluster Master: {_master_url()}\n\n"
            "Будет установлен/обновлён XFI Guard и Cluster Agent.\n"
            "Credentials передаются по SSH и не выводятся в Telegram.\n\n"
            "Продолжить?",
            reply_markup=_confirm_kb(),
        )

    @dp.callback_query(AddVPSStates.confirm, F.data == "cluster:add:cancel")
    async def add_cancel(c: CallbackQuery, state: FSMContext):
        if not authorized(c):
            return await c.answer("Нет доступа", show_alert=True)
        await state.clear()
        await c.message.answer("❌ Добавление VPS отменено.")
        await c.answer()

    @dp.callback_query(AddVPSStates.confirm, F.data == "cluster:add:install")
    async def add_install(c: CallbackQuery, state: FSMContext):
        if not authorized(c):
            return await c.answer("Нет доступа", show_alert=True)
        data = await state.get_data()
        host = data.get("host", "")
        port = int(data.get("port", 22))
        user = data.get("user", "root")
        master = _master_url()
        token = os.getenv("XFI_GUARD_CLUSTER_TOKEN", "").strip()
        secret = os.getenv("XFI_GUARD_CLUSTER_SECRET", "").strip()
        if not (host and master and token and secret):
            await state.clear()
            return await c.answer("Конфигурация кластера неполная", show_alert=True)
        try:
            _validate_master_url(master)
        except RuntimeError as exc:
            return await c.answer(str(exc), show_alert=True)

        await c.message.edit_text(f"⏳ Подключаю VPS {host}...\n\nSSH → установка → Cluster Agent → heartbeat.")
        try:
            ok, output = await asyncio.to_thread(
                bootstrap, host, user, port, 60, None,
                node_id=host, cluster_master=master,
                cluster_secret=secret, cluster_token=token,
            )
        except Exception as exc:
            ok, output = False, f"{type(exc).__name__}: {exc}"
        finally:
            await state.clear()

        safe = output[-1800:].replace(token, "<TOKEN>").replace(secret, "<SECRET>")
        if ok:
            await c.message.answer(
                f"🟢 VPS {host} подключён.\n\n{safe}\n\n"
                "Ожидаю heartbeat. Нажмите «🖥 VPS-узлы» → «🔄 Обновить»."
            )
            await c.answer("VPS подключён")
        else:
            await c.message.answer(
                f"🔴 Не удалось подключить VPS {host}.\n\n{safe}\n\n"
                "Проверьте SSH-доступ, known_hosts и права ключа."
            )
            await c.answer("Ошибка подключения", show_alert=True)
