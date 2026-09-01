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
    master_url = State()
    host = State()
    port = State()
    user = State()
    confirm = State()


def _cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cluster:add:cancel")],
    ])


def _confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Установить и подключить", callback_data="cluster:add:install")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cluster:add:cancel")],
    ])


def _master_url() -> str:
    return os.getenv("XFI_GUARD_CLUSTER_MASTER_URL", "").strip().rstrip("/")


def _credentials_ready() -> bool:
    return bool(os.getenv("XFI_GUARD_CLUSTER_TOKEN", "").strip() and os.getenv("XFI_GUARD_CLUSTER_SECRET", "").strip())


def _normalize_master_input(value: str) -> str:
    """Accept a full URL or a bare hostname entered by an administrator."""
    value = value.strip().rstrip("/")
    if not value:
        raise RuntimeError("XFI_GUARD_CLUSTER_MASTER_URL имеет некорректный формат")
    if "://" not in value:
        value = "https://" + value
    return value


def _validate_master_or_error(url: str) -> str:
    url = _normalize_master_input(url)
    _validate_master_url(url)
    return url


def _abort_text(text: str) -> bool:
    return (text or "").strip().lower() in {
        "/cancel", "cancel", "❌ отмена", "/start", "помощь", "🛡 защита",
        "🌐 кластер", "🌐 cluster center", "🏠 главное меню",
    }


async def _abort_if_requested(message: Message, state: FSMContext) -> bool:
    if not _abort_text(message.text or ""):
        return False
    await state.clear()
    await message.answer("❌ Добавление VPS отменено.")
    return True


def install_cluster_add_handlers(dp) -> None:
    @dp.callback_query(F.data == "cluster:add")
    async def add_start(c: CallbackQuery, state: FSMContext):
        if not authorized(c):
            return await c.answer("Нет доступа", show_alert=True)
        if not _credentials_ready():
            return await c.answer("Cluster credentials не настроены", show_alert=True)
        master = _master_url()
        await state.clear()
        if master:
            try:
                master = _validate_master_or_error(master)
            except RuntimeError as exc:
                return await c.answer(str(exc), show_alert=True)
        else:
            await state.set_state(AddVPSStates.master_url)
            await c.message.answer(
                "🌐 CLUSTER MASTER URL\n\n"
                "Введите URL, по которому новый VPS сможет достучаться до Cluster Master.\n\n"
                "Можно ввести полный URL:\n"
                "https://ger.deilja.online\n\n"
                "или только hostname:\n"
                "ger.deilja.online\n\n"
                "Для приватной сети допускается http://10.70.0.10:8765.",
                reply_markup=_cancel_kb(),
            )
            return await c.answer()
        await state.update_data(master_url=master)
        await state.set_state(AddVPSStates.host)
        await c.message.answer(
            "➕ ДОБАВЛЕНИЕ VPS\n\n"
            "Введите IP-адрес или hostname нового VPS.\n\n"
            "SSH должен быть доступен с Cluster Master, а ключ — уже находиться в SSH agent/known_hosts.",
            reply_markup=_cancel_kb(),
        )
        await c.answer()

    @dp.message(AddVPSStates.master_url)
    async def add_master_url(message: Message, state: FSMContext):
        if not authorized(message) or await _abort_if_requested(message, state):
            return
        try:
            master = _validate_master_or_error(message.text or "")
        except RuntimeError as exc:
            return await message.answer(f"❌ {exc}\nПовторите ввод URL.", reply_markup=_cancel_kb())
        await state.update_data(master_url=master)
        await state.set_state(AddVPSStates.host)
        await message.answer("Введите IP-адрес или hostname нового VPS:", reply_markup=_cancel_kb())

    @dp.message(AddVPSStates.host)
    async def add_host(message: Message, state: FSMContext):
        if not authorized(message) or await _abort_if_requested(message, state):
            return
        host = (message.text or "").strip()
        if not host or any(ch.isspace() for ch in host) or len(host) > 255:
            return await message.answer("❌ Некорректный IP/hostname. Повторите ввод.", reply_markup=_cancel_kb())
        await state.update_data(host=host)
        await state.set_state(AddVPSStates.port)
        await message.answer("Введите SSH-порт VPS (по умолчанию 22):", reply_markup=_cancel_kb())

    @dp.message(AddVPSStates.port)
    async def add_port(message: Message, state: FSMContext):
        if not authorized(message) or await _abort_if_requested(message, state):
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
            return await message.answer("❌ Порт должен быть числом от 1 до 65535.", reply_markup=_cancel_kb())
        await state.update_data(port=port)
        await state.set_state(AddVPSStates.user)
        await message.answer("Введите SSH-пользователя (по умолчанию root):", reply_markup=_cancel_kb())

    @dp.message(AddVPSStates.user)
    async def add_user(message: Message, state: FSMContext):
        if not authorized(message) or await _abort_if_requested(message, state):
            return
        user = (message.text or "").strip() or "root"
        if any(ch.isspace() for ch in user) or len(user) > 64:
            return await message.answer("❌ Некорректное имя SSH-пользователя.", reply_markup=_cancel_kb())
        data = await state.update_data(user=user)
        await state.set_state(AddVPSStates.confirm)
        await message.answer(
            "🧩 ПОДКЛЮЧЕНИЕ VPS\n\n"
            f"Host: {data['host']}\n"
            f"SSH: {user}@{data['host']}:{data['port']}\n"
            f"Cluster Master: {data['master_url']}\n\n"
            "Будет установлен/обновлён XFI Guard и Cluster Agent.\n"
            "Credentials передаются по SSH и не выводятся в Telegram.\n\n"
            "Продолжить?",
            reply_markup=_confirm_kb(),
        )

    @dp.callback_query(F.data == "cluster:add:cancel")
    async def add_cancel(c: CallbackQuery, state: FSMContext):
        if not authorized(c):
            return await c.answer("Нет доступа", show_alert=True)
        await state.clear()
        await c.message.answer("❌ Добавление VPS отменено.")
        await c.answer("Отменено")

    @dp.callback_query(AddVPSStates.confirm, F.data == "cluster:add:install")
    async def add_install(c: CallbackQuery, state: FSMContext):
        if not authorized(c):
            return await c.answer("Нет доступа", show_alert=True)
        data = await state.get_data()
        host = data.get("host", "")
        port = int(data.get("port", 22))
        user = data.get("user", "root")
        master = data.get("master_url", "")
        token = os.getenv("XFI_GUARD_CLUSTER_TOKEN", "").strip()
        secret = os.getenv("XFI_GUARD_CLUSTER_SECRET", "").strip()
        if not (host and master and token and secret):
            await state.clear()
            return await c.answer("Конфигурация кластера неполная", show_alert=True)
        try:
            _validate_master_or_error(master)
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
