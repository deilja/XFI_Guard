"""Telegram FSM for multi-VPS administration."""
from __future__ import annotations
import asyncio
from aiogram import F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup
from .nodes import collect_nodes, enroll_host_key, host_key_fingerprint, Node
from .nodes_manager import add_node, list_configured_nodes, remove_node
from .node_bootstrap import bootstrap
from .password_bootstrap import bootstrap_with_password
class NodeForm(StatesGroup):
    name=State(); host=State(); user=State(); port=State(); hostkey_confirm=State(); password=State(); password_confirm=State()
def _menu(): return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="➕ Добавить VPS"),KeyboardButton(text="🔐 Добавить по паролю")],[KeyboardButton(text="🗑 Удалить VPS")],[KeyboardButton(text="🔌 Подключить XFI Guard")],[KeyboardButton(text="🔄 Проверить VPS"),KeyboardButton(text="⬅️ Главное меню")]],resize_keyboard=True,is_persistent=True)
def _key_menu(): return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="✅ Доверять ключу")],[KeyboardButton(text="❌ Отмена")]],resize_keyboard=True,is_persistent=True)
def install_node_handlers(dp,admin_ids:set[int]):
    def ok(m): return bool(m.from_user and m.from_user.id in admin_ids)
    @dp.message(F.text=="🖥 VPS узлы")
    async def nodes_menu(m,state:FSMContext):
        if not ok(m): return
        await state.clear(); ns=list_configured_nodes(); rows=["🖥 VPS УЗЛЫ","",f"Настроено: {len(ns)}"]+[f"• {n.get('name')} — {n.get('user','root')}@{n.get('host')}:{n.get('port',22)}" for n in ns]
        if not ns: rows.append("• узлов пока нет")
        rows += ["","SSH: ключ XFI Guard / known_hosts","Пароли после регистрации не сохраняются."]
        await m.answer("\n".join(rows),reply_markup=_menu())
    @dp.message(F.text.in_({"➕ Добавить VPS","🔐 Добавить по паролю"}))
    async def add_start(m,state:FSMContext):
        if not ok(m): return
        await state.clear(); await state.update_data(password_mode=m.text=="🔐 Добавить по паролю"); await state.set_state(NodeForm.name); await m.answer("➕ Добавление VPS\n\nВведите имя узла, например: vps-de")
    @dp.message(F.text=="🗑 Удалить VPS")
    async def remove_start(m,state:FSMContext):
        if not ok(m): return
        ns=[str(x.get("name")) for x in list_configured_nodes()]
        if not ns: return await m.answer("Нет настроенных VPS.",reply_markup=_menu())
        await state.clear(); await state.update_data(remove_mode=True); await state.set_state(NodeForm.name); await m.answer("Введите имя VPS для удаления:\n\n"+"\n".join(f"• {x}" for x in ns))
    # Do not register a local "⬅️ Главное меню" handler here.
    # The global bot.py handler must own this button so it returns to main_kb(),
    # rather than reopening the VPS keyboard.
    @dp.message(NodeForm.name)
    async def node_name(m,state:FSMContext):
        if not ok(m): return
        text=(m.text or "").strip(); data=await state.get_data()
        if not text: return await m.answer("❌ Имя VPS не может быть пустым.")
        if data.get("remove_mode"):
            try: await asyncio.to_thread(remove_node,text); await state.clear(); await m.answer("✅ VPS удалён.",reply_markup=_menu())
            except Exception as e: await state.clear(); await m.answer(f"❌ {type(e).__name__}: {e}",reply_markup=_menu())
            return
        await state.update_data(name=text); await state.set_state(NodeForm.host); await m.answer("Введите IP или DNS имя VPS:")
    @dp.message(NodeForm.host)
    async def node_host(m,state:FSMContext):
        if not ok(m): return
        text=(m.text or "").strip()
        if not text or any(c in text for c in " /\\\t\r\n"): return await m.answer("❌ Некорректный IP/DNS. Повторите:")
        await state.update_data(host=text); await state.set_state(NodeForm.user); await m.answer("Введите SSH пользователя (по умолчанию root):")
    @dp.message(NodeForm.user)
    async def node_user(m,state:FSMContext):
        if not ok(m): return
        text=(m.text or "").strip()
        if text and any(c.isspace() for c in text): return await m.answer("❌ Некорректный SSH пользователь.")
        await state.update_data(user=text or "root"); await state.set_state(NodeForm.port); await m.answer("Введите SSH порт (по умолчанию 22):")
    @dp.message(NodeForm.port)
    async def node_port(m,state:FSMContext):
        if not ok(m): return
        try: port=int((m.text or "").strip() or 22)
        except ValueError: return await m.answer("❌ Порт должен быть числом 1..65535.")
        if not 1<=port<=65535: return await m.answer("❌ Порт должен быть 1..65535.")
        data=await state.get_data(); node=Node(name=data["name"],host=data["host"],user=data.get("user","root"),port=port); good,fp=await asyncio.to_thread(host_key_fingerprint,node)
        if not good: await state.clear(); return await m.answer(f"🟡 Host key не получен:\n{fp}",reply_markup=_menu())
        await state.update_data(port=port,fingerprint=fp); await state.set_state(NodeForm.hostkey_confirm); await m.answer(f"🔐 SSH host key\n\nVPS: {node.host}:{port}\nED25519: {fp}\n\nПроверьте fingerprint на VPS и подтвердите.",reply_markup=_key_menu())
    @dp.message(F.text=="❌ Отмена",NodeForm.hostkey_confirm)
    @dp.message(F.text=="❌ Отмена",NodeForm.password)
    @dp.message(F.text=="❌ Отмена",NodeForm.password_confirm)
    async def cancel_form(m,state:FSMContext):
        if ok(m): await state.clear(); await m.answer("❌ Добавление отменено.",reply_markup=_menu())
    @dp.message(F.text=="✅ Доверять ключу",NodeForm.hostkey_confirm)
    async def confirm_key(m,state:FSMContext):
        if not ok(m): return
        data=await state.get_data(); node=Node(name=data["name"],host=data["host"],user=data.get("user","root"),port=int(data["port"])); good,result=await asyncio.to_thread(enroll_host_key,node)
        if not good: await state.clear(); return await m.answer(f"❌ known_hosts: {result}",reply_markup=_menu())
        if data.get("password_mode"): await state.set_state(NodeForm.password); return await m.answer("🔑 Введите SSH пароль VPS.\n\nПароль используется только для первичного подключения и не сохраняется.",reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="❌ Отмена")]],resize_keyboard=True,is_persistent=True))
        try: await asyncio.to_thread(add_node,node.name,node.host,node.user,node.port); await state.clear(); await m.answer(f"✅ VPS добавлен.\n{node.user}@{node.host}:{node.port}",reply_markup=_menu())
        except Exception as e: await state.clear(); await m.answer(f"❌ {type(e).__name__}: {e}",reply_markup=_menu())
    @dp.message(NodeForm.password)
    async def password(m,state:FSMContext):
        if not ok(m): return
        password=m.text or ""
        if not password: return await m.answer("❌ Пароль пустой. Повторите:")
        try: await m.delete()
        except Exception: pass
        await state.update_data(password=password); await state.set_state(NodeForm.password_confirm); await m.answer("🔐 Пароль получен. Нажмите «🔌 Подключить».",reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🔌 Подключить")],[KeyboardButton(text="❌ Отмена")]],resize_keyboard=True,is_persistent=True))
    @dp.message(F.text=="🔌 Подключить",NodeForm.password_confirm)
    async def password_connect(m,state:FSMContext):
        if not ok(m): return
        data=await state.get_data(); password=data.get("password",""); node=Node(name=data["name"],host=data["host"],user=data.get("user","root"),port=int(data["port"])); await state.clear()
        try: good,out=await asyncio.to_thread(bootstrap_with_password,node.host,node.user,node.port,password)
        finally: password=""
        if not good: return await m.answer(f"❌ SSH подключение не выполнено:\n{out}",reply_markup=_menu())
        try: await asyncio.to_thread(add_node,node.name,node.host,node.user,node.port)
        except Exception as e: return await m.answer(f"❌ SSH успешен, но узел не сохранён: {type(e).__name__}: {e}",reply_markup=_menu())
        await m.answer(f"✅ VPS подключён\n\n{node.name}\nSSH: {node.user}@{node.host}:{node.port}\n\n🔑 SSH-ключ установлен.\n🔒 Пароль не сохранён.",reply_markup=_menu())
    @dp.message(F.text=="🔌 Подключить XFI Guard")
    async def bootstrap_menu(m):
        if not ok(m): return
        ns=list_configured_nodes()
        if not ns: return await m.answer("Сначала добавьте VPS.",reply_markup=_menu())
        await m.answer("⏳ Проверяю XFI Guard на настроенных VPS...")
        for n in ns:
            try: good,out=await asyncio.to_thread(bootstrap,n.get("host",""),n.get("user","root"),int(n.get("port",22)))
            except Exception as e: good,out=False,f"{type(e).__name__}: {e}"
            await m.answer(("🟢" if good else "🔴")+f" {n.get('name')}\n\n{out[-1800:]}")
    @dp.message(F.text=="🔄 Проверить VPS")
    async def probe(m):
        if not ok(m): return
        ns=await asyncio.to_thread(collect_nodes)
        if not ns: return await m.answer("VPS узлы не настроены.",reply_markup=_menu())
        lines=["🖥 Проверка VPS",""]
        for x in ns: lines += [("🟢" if x.get("status")=="online" else "🔴")+f" {x.get('name')} — {x.get('host')}",f"   XFI Guard: {x.get('xfi_guard','—')}; Fail2Ban: {x.get('fail2ban','—')}"]
        await m.answer("\n".join(lines)[:3900],reply_markup=_menu())
