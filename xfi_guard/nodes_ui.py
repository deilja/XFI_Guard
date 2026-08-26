"""Telegram FSM for multi-VPS administration."""
from __future__ import annotations
import asyncio, ipaddress, re
from aiogram import F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup
from .nodes import collect_nodes, enroll_host_key, host_key_fingerprint, Node, DEFAULT_IDENTITY_FILE, load_nodes, probe_node, restart_guard
from .nodes_manager import add_node, list_configured_nodes, remove_node
from .node_bootstrap import bootstrap
from .password_bootstrap import bootstrap_with_password
class NodeForm(StatesGroup):
    name=State(); host=State(); user=State(); port=State(); hostkey_confirm=State(); password=State(); password_confirm=State(); restart_confirm=State()
def _menu(): return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="➕ Добавить VPS"),KeyboardButton(text="🔐 Добавить по паролю")],[KeyboardButton(text="🗑 Удалить VPS")],[KeyboardButton(text="🔌 Подключить XFI Guard")],[KeyboardButton(text="🔄 Проверить VPS"),KeyboardButton(text="⬅️ Главное меню")]],resize_keyboard=True,is_persistent=True)
def _detail_menu(name): return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🔄 Обновить VPS")],[KeyboardButton(text="♻️ Перезапустить XFI Guard")],[KeyboardButton(text="⬅️ VPS узлы")],[KeyboardButton(text="⬅️ Главное меню")]],resize_keyboard=True,is_persistent=True)
def _confirm_menu(): return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="✅ Да, перезапустить")],[KeyboardButton(text="❌ Отмена")]],resize_keyboard=True,is_persistent=True)
def _key_menu(): return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="✅ Доверять ключу")],[KeyboardButton(text="❌ Отмена")]],resize_keyboard=True,is_persistent=True)
def _normalize_host(value: str)->tuple[str,int|None]:
    value=value.strip()
    if not value:return "",None
    m=re.fullmatch(r"\[([^\]]+)\]:(\d{1,5})",value)
    if m:return m.group(1),int(m.group(2))
    if value.count(":")==1:
        host,port=value.rsplit(":",1)
        if port.isdigit():return host,int(port)
    return value,None
def _valid_host(value:str)->bool:
    if len(value)>253 or any(c in value for c in " /\\\t\r\n"):return False
    try:ipaddress.ip_address(value);return True
    except ValueError:return bool(re.fullmatch(r"[A-Za-z0-9_.:-]+",value))
def _find_node(name):
    if not name:return None
    for n in load_nodes():
        if n.name==name:return n
    for n in list_configured_nodes():
        if str(n.get("name"))==name:return Node(name=name,host=n["host"],user=n.get("user","root"),port=int(n.get("port",22)),identity_file=n.get("identity_file") or str(DEFAULT_IDENTITY_FILE))
    return None
def _detail(x):
    return "\n".join([f"🟢 VPS: {x.get('name','—')}","",f"Host: {x.get('host','—')}",f"Status: {str(x.get('status','offline')).upper()}",f"Hostname: {x.get('hostname','—')}",f"XFI Guard: {x.get('xfi_guard','—')}",f"Fail2Ban: {x.get('fail2ban','—')}",f"UFW: {x.get('ufw','—')}",f"Load: {x.get('load','—')}",f"RAM: {x.get('memory','—') or '—'}",f"Disk /: {x.get('disk','—') or '—'}",f"Uptime: {x.get('uptime','—')}",f"Проверено: {x.get('checked_at','—')}",f"Ошибка: {x.get('error','нет')}"])
def install_node_handlers(dp,admin_ids:set[int]):
    def ok(m):return bool(m.from_user and m.from_user.id in admin_ids)
    @dp.message(F.text=="🖥 VPS узлы")
    async def nodes_menu(m,state:FSMContext):
        if not ok(m):return
        await state.clear();ns=list_configured_nodes();rows=["🖥 VPS УЗЛЫ","",f"Настроено: {len(ns)}"]+[f"• {n.get('name')} — {n.get('user','root')}@{n.get('host')}:{n.get('port',22)}" for n in ns]
        if not ns:rows.append("• узлов пока нет")
        rows += ["","SSH: ключ XFI Guard / known_hosts","Пароли после регистрации не сохраняются."]
        await m.answer("\n".join(rows),reply_markup=_menu())
        for n in ns:await m.answer(f"🖥 {n.get('name')}",reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=f"🔎 {n.get('name')}")]],resize_keyboard=True))
    @dp.message(F.text.regexp(r"^🔎 .+"))
    async def node_detail(m,state:FSMContext):
        if not ok(m):return
        name=m.text[2:].strip();node=_find_node(name)
        if not node:return await m.answer("❌ VPS не найден.",reply_markup=_menu())
        await state.clear()
        await state.update_data(detail_node=name)
        x=await asyncio.to_thread(probe_node,node)
        await m.answer(_detail(x),reply_markup=_detail_menu(name))
    @dp.message(F.text.in_({"🔄 Обновить","🔄 Обновить VPS"}))
    async def detail_refresh(m,state:FSMContext):
        if not ok(m):return
        data=await state.get_data();name=data.get("detail_node");node=_find_node(name)
        if not node:
            await state.clear()
            return await m.answer("❌ Карточка VPS устарела. Откройте VPS заново через «🖥 VPS узлы».",reply_markup=_menu())
        x=await asyncio.to_thread(probe_node,node)
        await state.update_data(detail_node=node.name)
        await m.answer(_detail(x),reply_markup=_detail_menu(node.name))
    @dp.message(F.text=="♻️ Перезапустить XFI Guard")
    async def restart_start(m,state:FSMContext):
        if not ok(m):return
        data=await state.get_data();node=_find_node(data.get("detail_node"))
        if not node:return await m.answer("❌ VPS не выбран.",reply_markup=_menu())
        await state.set_state(NodeForm.restart_confirm);await m.answer(f"⚠️ Подтвердите перезапуск XFI Guard на VPS {node.name}.\n\nБудет выполнено только:\nsudo -n systemctl restart xfi-guard.service",reply_markup=_confirm_menu())
    @dp.message(F.text=="❌ Отмена",NodeForm.restart_confirm)
    async def restart_cancel(m,state:FSMContext):
        if ok(m):
            data=await state.get_data();node=_find_node(data.get("detail_node"));await state.set_state(None);await m.answer("Отменено.",reply_markup=_detail_menu(node.name) if node else _menu())
    @dp.message(F.text=="✅ Да, перезапустить",NodeForm.restart_confirm)
    async def restart_confirm(m,state:FSMContext):
        if not ok(m):return
        data=await state.get_data();node=_find_node(data.get("detail_node"));await state.clear()
        if not node:return await m.answer("❌ VPS не найден.",reply_markup=_menu())
        good,result=await asyncio.to_thread(restart_guard,node);x=await asyncio.to_thread(probe_node,node);await state.update_data(detail_node=node.name) if False else None;await m.answer(("🟢 " if good else "🔴 ")+result+"\n\n"+_detail(x),reply_markup=_detail_menu(node.name))
    @dp.message(F.text=="⬅️ VPS узлы")
    async def back_nodes(m,state:FSMContext):
        if ok(m):await state.clear();await nodes_menu(m,state)
    @dp.message(F.text.in_({"➕ Добавить VPS","🔐 Добавить по паролю"}))
    async def add_start(m,state:FSMContext):
        if not ok(m): return
        await state.clear(); await state.update_data(password_mode=m.text=="🔐 Добавить по паролю"); await state.set_state(NodeForm.name); await m.answer("➕ Добавление VPS\n\nВведите имя узла, например: vps-de")
    @dp.message(F.text=="🗑 Удалить VPS")
    async def remove_start(m,state:FSMContext):
        if not ok(m): return
        ns=[str(x.get("name")) for x in list_configured_nodes()]
        if not ns:return await m.answer("Нет настроенных VPS.",reply_markup=_menu())
        await state.clear(); await state.update_data(remove_mode=True); await state.set_state(NodeForm.name); await m.answer("Введите имя VPS для удаления:\n\n"+"\n".join(f"• {x}" for x in ns))
    @dp.message(NodeForm.name)
    async def node_name(m,state:FSMContext):
        if not ok(m):return
        text=(m.text or "").strip(); data=await state.get_data()
        if not text:return await m.answer("❌ Имя VPS не может быть пустым.")
        if data.get("remove_mode"):
            try: await asyncio.to_thread(remove_node,text); await state.clear(); await m.answer("✅ VPS удалён.",reply_markup=_menu())
            except Exception as e: await state.clear(); await m.answer(f"❌ {type(e).__name__}: {e}",reply_markup=_menu())
            return
        await state.update_data(name=text); await state.set_state(NodeForm.host); await m.answer("Введите IP или DNS имя VPS.\nМожно указать сразу с портом, например: 2.27.37.78:22")
    @dp.message(NodeForm.host)
    async def node_host(m,state:FSMContext):
        if not ok(m):return
        raw=(m.text or "").strip(); host,embedded_port=_normalize_host(raw)
        if not host or not _valid_host(host):return await m.answer("❌ Некорректный IP/DNS. Пример: 2.27.37.78 или vps.example.com:22")
        await state.update_data(host=host,embedded_port=embedded_port); await state.set_state(NodeForm.user); await m.answer("Введите SSH пользователя (по умолчанию root):")
    @dp.message(NodeForm.user)
    async def node_user(m,state:FSMContext):
        if not ok(m):return
        text=(m.text or "").strip()
        if text and any(c.isspace() for c in text):return await m.answer("❌ Некорректный SSH пользователь.")
        await state.update_data(user=text or "root"); await state.set_state(NodeForm.port); data=await state.get_data(); default_port=data.get("embedded_port") or 22; await m.answer(f"Введите SSH порт (по умолчанию {default_port}):")
    @dp.message(NodeForm.port)
    async def node_port(m,state:FSMContext):
        if not ok(m):return
        data=await state.get_data()
        try:port=int((m.text or "").strip() or data.get("embedded_port") or 22)
        except ValueError:return await m.answer("❌ Порт должен быть числом 1..65535.")
        if not 1<=port<=65535:return await m.answer("❌ Порт должен быть 1..65535.")
        node=Node(name=data["name"],host=data["host"],user=data.get("user","root"),port=port); good,fp=await asyncio.to_thread(host_key_fingerprint,node)
        if not good:return await m.answer(f"🟡 Host key не получен:\n{fp}\n\nПроверьте IP/порт и доступность SSH, затем повторите ввод.")
        await state.update_data(port=port,fingerprint=fp); await state.set_state(NodeForm.hostkey_confirm); await m.answer(f"🔐 SSH host key\n\nVPS: {node.host}:{port}\nED25519: {fp}\n\nПроверьте fingerprint на VPS и подтвердите.",reply_markup=_key_menu())
    @dp.message(F.text=="❌ Отмена",NodeForm.hostkey_confirm)
    @dp.message(F.text=="❌ Отмена",NodeForm.password)
    @dp.message(F.text=="❌ Отмена",NodeForm.password_confirm)
    async def cancel_form(m,state:FSMContext):
        if ok(m):await state.clear();await m.answer("❌ Добавление отменено.",reply_markup=_menu())
    @dp.message(F.text=="✅ Доверять ключу",NodeForm.hostkey_confirm)
    async def confirm_key(m,state:FSMContext):
        if not ok(m):return
        data=await state.get_data(); node=Node(name=data["name"],host=data["host"],user=data.get("user","root"),port=int(data["port"])); good,result=await asyncio.to_thread(enroll_host_key,node)
        if not good:await state.clear();return await m.answer(f"❌ known_hosts: {result}",reply_markup=_menu())
        if data.get("password_mode"):
            await state.set_state(NodeForm.password);return await m.answer("🔑 Введите SSH пароль VPS.\n\nПароль используется только для первичного подключения и не сохраняется.",reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="❌ Отмена")]],resize_keyboard=True,is_persistent=True))
        try:await asyncio.to_thread(add_node,node.name,node.host,node.user,node.port)
        except Exception as e:await state.clear();await m.answer(f"❌ {type(e).__name__}: {e}",reply_markup=_menu());return
        await state.clear();await m.answer(f"✅ VPS добавлен.\n{node.user}@{node.host}:{node.port}",reply_markup=_menu())
    @dp.message(NodeForm.password)
    async def password(m,state:FSMContext):
        if not ok(m):return
        password=m.text or ""
        if not password:return await m.answer("❌ Пароль пустой. Повторите:")
        try:await m.delete()
        except Exception:pass
        await state.update_data(password=password);await state.set_state(NodeForm.password_confirm);await m.answer("🔐 Пароль получен. Нажмите «🔌 Подключить».",reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🔌 Подключить")],[KeyboardButton(text="❌ Отмена")]],resize_keyboard=True,is_persistent=True))
    @dp.message(F.text=="🔌 Подключить",NodeForm.password_confirm)
    async def password_connect(m,state:FSMContext):
        if not ok(m):return
        data=await state.get_data();password=data.get("password","");node=Node(name=data["name"],host=data["host"],user=data.get("user","root"),port=int(data["port"]));await state.clear()
        try:good,out=await asyncio.to_thread(bootstrap_with_password,node.host,node.user,node.port,password)
        finally:password=""
        if not good:return await m.answer(f"❌ SSH подключение не выполнено:\n{out}",reply_markup=_menu())
        try:await asyncio.to_thread(add_node,node.name,node.host,node.user,node.port,str(DEFAULT_IDENTITY_FILE))
        except Exception as e:return await m.answer(f"❌ SSH успешен, но узел не сохранён: {type(e).__name__}: {e}",reply_markup=_menu())
        await m.answer(f"✅ VPS подключён\n\n{node.name}\nSSH: {node.user}@{node.host}:{node.port}\n\n🔑 SSH-ключ установлен.\n🔒 Пароль не сохранён.",reply_markup=_menu())
    @dp.message(F.text=="🔌 Подключить XFI Guard")
    async def bootstrap_menu(m):
        if not ok(m):return
        ns=list_configured_nodes()
        if not ns:return await m.answer("Сначала добавьте VPS.",reply_markup=_menu())
        await m.answer("⏳ Проверяю XFI Guard на настроенных VPS...")
        for n in ns:
            identity=n.get("identity_file") or str(DEFAULT_IDENTITY_FILE)
            try:good,out=await asyncio.to_thread(bootstrap,n.get("host",""),n.get("user","root"),int(n.get("port",22)),30,identity)
            except Exception as e:good,out=False,f"{type(e).__name__}: {e}"
            await m.answer(("🟢" if good else "🔴")+f" {n.get('name')}\n\n{out[-1800:]}")
    @dp.message(F.text=="🔄 Проверить VPS")
    async def probe(m):
        if not ok(m):return
        ns=await asyncio.to_thread(collect_nodes)
        if not ns:return await m.answer("VPS узлы не настроены.",reply_markup=_menu())
        lines=["🖥 Проверка VPS",""]
        for x in ns:lines += [("🟢" if x.get("status")=="online" else "🔴")+f" {x.get('name')} — {x.get('host')}",f"   XFI Guard: {x.get('xfi_guard','—')}; Fail2Ban: {x.get('fail2ban','—')}" ]
        await m.answer("\n".join(lines)[:3900],reply_markup=_menu())
