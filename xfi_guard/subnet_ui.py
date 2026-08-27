"""Telegram admin UI for explicit IPv4 subnet blocking."""
from __future__ import annotations

import ipaddress
from aiogram import F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from .subnet_blocker import block_subnet, list_blocked_subnets, unblock_subnet


BACK_TEXT = "⬅️ Главное меню"


class SubnetStates(StatesGroup):
    block = State()
    unblock = State()


def subnet_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Заблокировать подсеть")],
            [KeyboardButton(text="➖ Разблокировать подсеть")],
            [KeyboardButton(text="📋 Подсети в блокировке")],
            [KeyboardButton(text=BACK_TEXT)],
        ], resize_keyboard=True, is_persistent=True,
    )


def install_subnet_handlers(dp, admin_ids, main_kb):
    @dp.message(F.text == "➕ Заблокировать подсеть")
    async def subnet_block_start(message, state: FSMContext):
        if not message.from_user or message.from_user.id not in admin_ids:
            return
        await state.set_state(SubnetStates.block)
        await message.answer(
            "➕ Блокировка подсети\n\nВведите публичную IPv4 подсеть в CIDR, например: 1.2.3.0/24.\nРазрешены сети не шире /24.",
            reply_markup=subnet_menu(),
        )

    @dp.message(SubnetStates.block)
    async def subnet_block_save(message, state: FSMContext):
        if not message.from_user or message.from_user.id not in admin_ids:
            return
        value = (message.text or "").strip()
        if value == BACK_TEXT:
            await state.clear()
            await message.answer("🏠 Главное меню", reply_markup=main_kb())
            return
        try:
            network = ipaddress.ip_network(value, strict=False)
            if network.version != 4 or network.prefixlen < 24 or not network.is_global:
                raise ValueError
            canonical = network.with_prefixlen
        except ValueError:
            await message.answer("❌ Некорректная подсеть. Нужна публичная IPv4 CIDR не шире /24.", reply_markup=subnet_menu())
            return
        ok, result = block_subnet(canonical)
        await state.clear()
        await message.answer(("✅ " if ok else "❌ ") + result, reply_markup=subnet_menu())

    @dp.message(F.text == "➖ Разблокировать подсеть")
    async def subnet_unblock_start(message, state: FSMContext):
        if not message.from_user or message.from_user.id not in admin_ids:
            return
        await state.set_state(SubnetStates.unblock)
        await message.answer("➖ Введите IPv4 подсеть CIDR для разблокировки, например: 1.2.3.0/24.", reply_markup=subnet_menu())

    @dp.message(SubnetStates.unblock)
    async def subnet_unblock_save(message, state: FSMContext):
        if not message.from_user or message.from_user.id not in admin_ids:
            return
        value = (message.text or "").strip()
        if value == BACK_TEXT:
            await state.clear()
            await message.answer("🏠 Главное меню", reply_markup=main_kb())
            return
        try:
            network = ipaddress.ip_network(value, strict=False)
            if network.version != 4 or network.prefixlen < 24 or not network.is_global:
                raise ValueError
            canonical = network.with_prefixlen
        except ValueError:
            await message.answer("❌ Некорректная подсеть.", reply_markup=subnet_menu())
            return
        ok, result = unblock_subnet(canonical)
        await state.clear()
        await message.answer(("✅ " if ok else "❌ ") + result, reply_markup=subnet_menu())

    @dp.message(F.text == "📋 Подсети в блокировке")
    async def subnet_list(message):
        if not message.from_user or message.from_user.id not in admin_ids:
            return
        items = list_blocked_subnets()
        text = "🛡 ЗАБЛОКИРОВАННЫЕ ПОДСЕТИ\n\n" + ("\n".join(f"• {x}" for x in items[:100]) if items else "• нет")
        await message.answer(text[:3900], reply_markup=subnet_menu())
