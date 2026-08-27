"""Telegram admin UI for explicit IPv4 subnet blocking."""
from __future__ import annotations
import ipaddress
from aiogram import F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State,StatesGroup
from aiogram.types import KeyboardButton,ReplyKeyboardMarkup
from .admin_auth import authorized
from .subnet_blocker import block_subnet,list_blocked_subnets,unblock_subnet
BACK_TEXT="⬅️ Главное меню"
class SubnetStates(StatesGroup): block=State();unblock=State()
def subnet_menu():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="➕ Заблокировать подсеть")],[KeyboardButton(text="➖ Разблокировать подсеть")],[KeyboardButton(text="📋 Подсети в блокировке")],[KeyboardButton(text=BACK_TEXT)]],resize_keyboard=True,is_persistent=True)
def _valid_network(value):
    try:
        network=ipaddress.ip_network(value,strict=False)
        if network.version!=4 or network.prefixlen<24 or not network.is_global: return None
        return network.with_prefixlen
    except ValueError:return None
def install_subnet_handlers(dp,admin_ids,main_kb):
    @dp.message(F.text=="➕ Заблокировать подсеть")
    async def subnet_block_start(message,state:FSMContext):
        if not authorized(message):return
        await state.set_state(SubnetStates.block);await message.answer("➕ Блокировка подсети\n\nВведите публичную IPv4 подсеть в CIDR, например: 1.2.3.0/24.\nРазрешены сети не шире /24.",reply_markup=subnet_menu())
    @dp.message(SubnetStates.block)
    async def subnet_block_save(message,state:FSMContext):
        if not authorized(message):return
        value=(message.text or "").strip()
        if value==BACK_TEXT:await state.clear();await message.answer("🏠 Главное меню",reply_markup=main_kb());return
        canonical=_valid_network(value)
        if not canonical:await message.answer("❌ Некорректная подсеть. Нужна публичная IPv4 CIDR не шире /24.",reply_markup=subnet_menu());return
        try:ok,result=block_subnet(canonical)
        except (ValueError,OSError):ok,result=False,"Операция не выполнена."
        await state.clear();await message.answer(("✅ " if ok else "❌ ")+str(result)[:3500],reply_markup=subnet_menu())
    @dp.message(F.text=="➖ Разблокировать подсеть")
    async def subnet_unblock_start(message,state:FSMContext):
        if not authorized(message):return
        await state.set_state(SubnetStates.unblock);await message.answer("➖ Введите IPv4 подсеть CIDR для разблокировки, например: 1.2.3.0/24.",reply_markup=subnet_menu())
    @dp.message(SubnetStates.unblock)
    async def subnet_unblock_save(message,state:FSMContext):
        if not authorized(message):return
        value=(message.text or "").strip()
        if value==BACK_TEXT:await state.clear();await message.answer("🏠 Главное меню",reply_markup=main_kb());return
        canonical=_valid_network(value)
        if not canonical:await message.answer("❌ Некорректная подсеть.",reply_markup=subnet_menu());return
        try:ok,result=unblock_subnet(canonical)
        except (ValueError,OSError):ok,result=False,"Операция не выполнена."
        await state.clear();await message.answer(("✅ " if ok else "❌ ")+str(result)[:3500],reply_markup=subnet_menu())
    @dp.message(F.text=="📋 Подсети в блокировке")
    async def subnet_list(message):
        if not authorized(message):return
        try:items=list_blocked_subnets()
        except (OSError,ValueError):items=[]
        text="🛡 ЗАБЛОКИРОВАННЫЕ ПОДСЕТИ\n\n"+("\n".join(f"• {x}" for x in items[:100]) if items else "• нет");await message.answer(text[:3900],reply_markup=subnet_menu())
