"""Telegram Cluster Center for XFI Guard."""
from __future__ import annotations
import asyncio,json,os,socket,hmac,hashlib,urllib.error,urllib.request
from pathlib import Path
from urllib.parse import urlsplit
from aiogram import F
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardButton,InlineKeyboardMarkup
from .admin_auth import authorized
from .cluster_status import cluster_summary
from .nodes import load_nodes,probe_node,restart_guard
STATE_PATH=Path(os.getenv("XFI_GUARD_CLUSTER_STATE",str(Path.home()/".cache/xfi-guard/cluster-state.json")))
DEFAULT_MASTER_URL="http://127.0.0.1:8765"
def _master_url(): return os.getenv("XFI_GUARD_CLUSTER_MASTER_URL",DEFAULT_MASTER_URL).strip().rstrip("/") or DEFAULT_MASTER_URL
def _validate_master_url(url:str)->str:
    p=urlsplit(url)
    if p.scheme not in {"http","https"} or not p.hostname or p.username or p.password: raise RuntimeError("XFI_GUARD_CLUSTER_MASTER_URL имеет некорректный формат")
    if p.scheme=="http" and p.hostname not in {"127.0.0.1","localhost","::1"}: raise RuntimeError("Для удалённого Cluster Master требуется HTTPS")
    return url
def _timeout():
    try:return max(1.,min(15.,float(os.getenv("XFI_GUARD_CLUSTER_TIMEOUT","5"))))
    except ValueError:return 5.
def _request(path):
    base=_validate_master_url(_master_url());req=urllib.request.Request(base+path,method="GET");token=os.getenv("XFI_GUARD_CLUSTER_TOKEN","").strip()
    if not token:raise RuntimeError("XFI_GUARD_CLUSTER_TOKEN не задан")
    req.add_header("Authorization",f"Bearer {token}")
    try:
        with urllib.request.urlopen(req,timeout=_timeout()) as r:
            data=json.loads(r.read().decode())
            if getattr(r,"status",200)>=400:raise RuntimeError(data.get("error","HTTP error"))
            return data
    except urllib.error.HTTPError as exc:
        try:detail=json.loads(exc.read().decode()).get("error","")
        except Exception:detail=""
        raise RuntimeError(f"HTTP {exc.code}"+(f": {detail}" if detail else "")) from exc
def _master_diagnostic(exc):
    url=_master_url();p=urlsplit(url);host=p.hostname or "";port=p.port or (443 if p.scheme=="https" else 80)
    if not host:return f"URL: {url}\n🔴 DNS/URL: некорректный адрес"
    try:
        with socket.create_connection((host,port),timeout=2):tcp="🟢 TCP: доступен"
    except socket.gaierror as e:return f"URL: {url}\n🔴 DNS: {e}"
    except ConnectionRefusedError:return f"URL: {url}\n🔴 TCP: Connection refused — порт {port} не принимает соединения"
    except TimeoutError:return f"URL: {url}\n🔴 TCP: timeout — узел не отвечает"
    except OSError as e:return f"URL: {url}\n🔴 TCP: недоступен ({e})"
    return f"URL: {url}\n{tcp}\n🔴 HTTP: {type(exc).__name__}: {exc}"
def _callback_secret()->bytes:
    value=os.getenv("XFI_GUARD_CLUSTER_TOKEN","").strip()
    if not value: raise RuntimeError("XFI_GUARD_CLUSTER_TOKEN не задан")
    return value.encode("utf-8")
def _node_ref(name:str)->str:
    digest=hmac.new(_callback_secret(),name.encode("utf-8"),hashlib.sha256).hexdigest()[:20]
    return digest
def _resolve_node_ref(ref:str):
    for node in load_nodes():
        if hmac.compare_digest(_node_ref(node.name),ref): return node
    return None
def _buttons(): return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔄 Обновить",callback_data="cluster:refresh")],[InlineKeyboardButton(text="🖥 VPS-узлы",callback_data="cluster:nodes")],[InlineKeyboardButton(text="🌐 Глобальные блокировки",callback_data="cluster:blocks")],[InlineKeyboardButton(text="⬅️ Главное меню",callback_data="cluster:menu")]])
def _state_blocks():
    try:return json.loads(STATE_PATH.read_text()).get("blocks",{})
    except (FileNotFoundError,OSError,ValueError):return {}
def _live_blocks():
    try:return list(_request("/blocks").get("blocks",[]))
    except Exception:return [{"ip":ip,**item} for ip,item in _state_blocks().items()]
def _format_nodes(data):
    nodes=data.get("nodes",[]);summary=cluster_summary(nodes)
    if not nodes:return "• узлы ещё не зарегистрированы"
    lines=[]
    for n in nodes:
        s=n.get("status","offline");icon={"online":"🟢","degraded":"🟡","offline":"🔴"}.get(s,"⚪");name=n.get("name") or n.get("hostname") or "-";lines += [f"{icon} {name} — {s.upper()}",f"   heartbeat: {n.get('status_reason','-')} | 🔒 {len(n.get('blocked',[]))}"]
    c=summary["counts"];return "\n".join(lines+["",f"Итого: 🟢 {c['online']}  🟡 {c['degraded']}  🔴 {c['offline']}"])
def _local_node_data(): return [probe_node(n) for n in load_nodes()]
def _detail(x): return "\n".join([f"🖥 VPS: {x.get('name','—')}","",f"Host: {x.get('host','—')}",f"Status: {str(x.get('status','offline')).upper()}",f"Hostname: {x.get('hostname','—')}",f"XFI Guard: {x.get('xfi_guard','—')}",f"Fail2Ban: {x.get('fail2ban','—')}",f"UFW: {x.get('ufw','—')}",f"Load: {x.get('load','—')}",f"RAM: {x.get('memory','—')}",f"Disk /: {x.get('disk','—')}",f"Uptime: {x.get('uptime','—')}",f"Проверено: {x.get('checked_at','—')}",f"Ошибка: {x.get('error','нет')}"])
def _node_buttons(name,confirm=False):
    ref=_node_ref(name)
    if confirm:return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Да, перезапустить",callback_data=f"cluster:restart:{ref}")],[InlineKeyboardButton(text="❌ Отмена",callback_data=f"cluster:detail:{ref}")]])
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔄 Обновить",callback_data=f"cluster:detail:{ref}")],[InlineKeyboardButton(text="♻️ Перезапустить XFI Guard",callback_data=f"cluster:confirm_restart:{ref}")],[InlineKeyboardButton(text="⬅️ Cluster Center",callback_data="cluster:refresh")]])
def cluster_view():
    try:
        health=_request("/health");nodes=_request("/nodes");summary=cluster_summary(nodes.get("nodes",[]));blocks=_live_blocks();c=summary["counts"];return "\n".join(["🌐 XFI GUARD • CLUSTER CENTER","", "🟢 Cluster Master: ONLINE",f"{'🟢' if summary['status']=='online' else '🟡' if summary['status']=='degraded' else '🔴'} Cluster: {summary['status'].upper()}","",f"🖥 VPS: {summary['total']}",f"🟢 Online: {c['online']}",f"🟡 Degraded: {c['degraded']}",f"🔴 Offline: {c['offline']}",f"🚨 Активные угрозы: {int(health.get('threats',0))}",f"🔒 Глобальные IP: {len(blocks)}","","🛡 Политика","• AI consensus → авто-блок","• Fail2Ban → 7 дней","• Global sync → включена","• Heartbeat TTL: 90s"])
    except Exception as exc:return "🌐 XFI GUARD • CLUSTER CENTER\n\n🔴 Cluster Master недоступен.\n\n"+_master_diagnostic(exc)+"\n\nПроверьте xfi-guard-multi-vps-master.service и XFI_GUARD_CLUSTER_MASTER_URL."
def blocks_view():
    blocks=_live_blocks()
    if not blocks:return "🌐 ГЛОБАЛЬНЫЕ БЛОКИРОВКИ\n\nАктивных глобальных блокировок нет."
    lines=["🌐 ГЛОБАЛЬНЫЕ БЛОКИРОВКИ","",f"Всего: {len(blocks)}",""]
    for x in blocks[:40]:
        ns=x.get("nodes",{}) or {};lines += [f"🚫 {x.get('ip','-')}",f"   Источник: {x.get('source_node','-')}",f"   VPS: {sum(v=='blocked' for v in ns.values())} применено / {sum(v=='queued' for v in ns.values())} в очереди",f"   До: {x.get('until','-')}"]
    return "\n".join(lines+[f"… ещё {len(blocks)-40}"] if len(blocks)>40 else lines)[:3900]
async def _safe_edit(message,text,reply_markup):
    try: await message.edit_text(text,reply_markup=reply_markup)
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc).lower(): raise
def install_cluster_handlers(dp,main_kb):
    @dp.message(F.text.in_({"🌐 Кластер","🌐 Cluster Center"}))
    async def cluster_button(m):
        if authorized(m):await m.answer(cluster_view(),reply_markup=_buttons())
    @dp.callback_query(F.data=="cluster:refresh")
    async def refresh(c):
        if not authorized(c):return await c.answer("Нет доступа",show_alert=True)
        await _safe_edit(c.message,cluster_view(),_buttons());await c.answer("Кластер обновлён")
    @dp.callback_query(F.data=="cluster:nodes")
    async def nodes(c):
        if not authorized(c):return await c.answer("Нет доступа",show_alert=True)
        local=await asyncio.to_thread(_local_node_data)
        if local:text="🖥 VPS-УЗЛЫ\n\n"+"\n\n".join(_detail(x) for x in local);await _safe_edit(c.message,text[:3900],_buttons())
        else:await _safe_edit(c.message,"🖥 VPS-УЗЛЫ\n\n"+_format_nodes(_request("/nodes")),_buttons())
        await c.answer("VPS-узлы")
    @dp.callback_query(F.data.startswith("cluster:detail:"))
    async def detail(c):
        if not authorized(c):return await c.answer("Нет доступа",show_alert=True)
        ref=c.data.split(":",2)[2];node=_resolve_node_ref(ref)
        if not node:return await c.answer("VPS не найден",show_alert=True)
        x=await asyncio.to_thread(probe_node,node);await _safe_edit(c.message,_detail(x),_node_buttons(node.name));await c.answer("Обновлено")
    @dp.callback_query(F.data.startswith("cluster:confirm_restart:"))
    async def confirm_restart(c):
        if not authorized(c):return await c.answer("Нет доступа",show_alert=True)
        ref=c.data.split(":",2)[2];node=_resolve_node_ref(ref)
        if not node:return await c.answer("VPS не найден",show_alert=True)
        await _safe_edit(c.message,f"⚠️ Подтвердите перезапуск XFI Guard на VPS {node.name}.\n\nВыполнится только:\nsudo -n systemctl restart xfi-guard.service",_node_buttons(node.name,True));await c.answer()
    @dp.callback_query(F.data.startswith("cluster:restart:"))
    async def restart(c):
        if not authorized(c):return await c.answer("Нет доступа",show_alert=True)
        ref=c.data.split(":",2)[2];node=_resolve_node_ref(ref)
        if not node:return await c.answer("VPS не найден",show_alert=True)
        ok,msg=await asyncio.to_thread(restart_guard,node);x=await asyncio.to_thread(probe_node,node);await _safe_edit(c.message,("🟢 " if ok else "🔴 ")+msg+"\n\n"+_detail(x),_node_buttons(node.name));await c.answer("Готово" if ok else "Ошибка",show_alert=not ok)
    @dp.callback_query(F.data=="cluster:blocks")
    async def blocks(c):
        if not authorized(c):return await c.answer("Нет доступа",show_alert=True)
        await _safe_edit(c.message,blocks_view(),_buttons());await c.answer("Глобальные блокировки")
    @dp.callback_query(F.data=="cluster:menu")
    async def menu(c):
        if not authorized(c):return await c.answer("Нет доступа",show_alert=True)
        await _safe_edit(c.message,"🏠 Главное меню\n\nВыберите раздел в нижнем меню.",None);await c.answer()