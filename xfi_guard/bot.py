"""Telegram admin bot for XFI Guard. Интерфейс бота на русском языке."""
from __future__ import annotations
import asyncio, os, subprocess
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from .ai_ui import install_ai_handlers
from .ai_center import install_ai_center_handlers, ai_center_menu
from .ai_model_manager import install_ai_model_manager
from .ai_keys_ui import install_ai_key_handlers
from .openrouter_ui import install_openrouter_handlers
from .xui_ui import install_xui_handlers
from .alert_callbacks import register_alert_callbacks
from .attack_surface import collect_attack_surface
from .checks import collect_basic_checks
from .defense_ui import install_defense_handlers, defense_menu
from .firewall import list_blocked_ips
from .rate_limit import RateLimitMiddleware
from .security import collect_security_checks
from .vpn import collect_vpn_checks
from .nodes import collect_nodes
from .nodes_ui import install_node_handlers
from .cluster_ui import install_cluster_handlers

ADMIN_IDS={int(v) for v in os.getenv("XFI_GUARD_ADMIN_IDS","").split(",") if v.strip().isdigit()}
def admin(message): return bool(message.from_user and message.from_user.id in ADMIN_IDS)
def kb(rows): return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=x) for x in row] for row in rows],resize_keyboard=True,is_persistent=True)
def main_kb(): return kb([["📊 Статус","🛡 Защита","🌐 VPN/Xray"],["🤖 AI","🖥 VPS","🌐 Кластер"],["🚫 Блокировки","📋 События","⚙️ 3X-UI"],["🔄 Проверка","🔄 Обновить","❓ Помощь"]])
def results(items): return "\n".join(f"{getattr(x,'status','unknown').upper()}: {getattr(x,'name','check')} — {getattr(x,'message','')}" for x in items)[:3800] or "Нет данных."
def blocked_view():
    try:
        ips=list_blocked_ips(); lines=["🛡 АКТИВНЫЕ БЛОКИРОВКИ","",f"Всего: {len(ips)}","Срок автоматической блокировки: 7 дней","Backend: Fail2Ban + UFW","", "IP:"]
        lines.extend(f"• {ip}" for ip in ips[:100])
        if len(ips)>100: lines.append(f"… ещё {len(ips)-100} IP")
        if not ips: lines.append("• нет активных публичных IP-блокировок")
        return "\n".join(lines)[:3900]
    except Exception as exc: return f"❌ Не удалось получить список блокировок: {type(exc).__name__}: {exc}"

def build_dispatcher():
    dp=Dispatcher(storage=MemoryStorage()); rl=RateLimitMiddleware(rate=2,period=1.0); dp.message.middleware(rl); dp.callback_query.middleware(rl)
    register_alert_callbacks(dp,ADMIN_IDS); install_ai_handlers(dp); install_ai_key_handlers(dp); install_ai_model_manager(dp); install_ai_center_handlers(dp); install_openrouter_handlers(dp); install_xui_handlers(dp); install_defense_handlers(dp); install_node_handlers(dp,ADMIN_IDS); install_cluster_handlers(dp,ADMIN_IDS,main_kb)
    @dp.message(Command("start"))
    async def start(message,state:FSMContext):
        await state.clear()
        if admin(message): await message.answer("🛡 XFI Guard\n\nПанель управления сервером активна.",reply_markup=main_kb())
    @dp.message(Command("status"))
    async def status_command(message):
        if admin(message): await message.answer("📊 Статус XFI Guard\n\n"+results(collect_basic_checks()+collect_security_checks()+collect_vpn_checks()),reply_markup=main_kb())
    @dp.message(Command("blocked"))
    async def blocked_command(message):
        if admin(message): await message.answer(blocked_view(),reply_markup=main_kb())
    @dp.message(Command("vps"))
    async def vps_command(message):
        if not admin(message): return
        await message.answer(await vps_view(),reply_markup=main_kb())
    @dp.message(F.text=="📊 Статус")
    async def status_button(message): await status_command(message)
    @dp.message(F.text=="🛡 Защита")
    async def protection_button(message):
        if admin(message): await message.answer("🛡 ЗАЩИТА\n\nУправление Fail2Ban, UFW и ручными блокировками.",reply_markup=defense_menu())
    @dp.message(F.text=="🔐 Безопасность")
    async def security_button(message):
        if admin(message): await message.answer("🔐 Безопасность\n\n"+results(collect_security_checks()),reply_markup=main_kb())
    @dp.message(F.text=="🌐 VPN/Xray")
    async def vpn_button(message):
        if admin(message): await message.answer("🌐 VPN/Xray\n\n"+results(collect_vpn_checks()),reply_markup=main_kb())
    @dp.message(F.text.in_({"🖥 VPS","🖥 VPS узлы"}))
    async def vps_button(message):
        if admin(message): await message.answer(await vps_view(),reply_markup=main_kb())
    @dp.message(F.text.in_({"🌐 Кластер","🌐 Cluster Center"}))
    async def cluster_button(message):
        if admin(message): await message.answer(__import__("xfi_guard.cluster_ui",fromlist=["cluster_view"]).cluster_view(),reply_markup=main_kb())
    @dp.message(F.text=="🚫 Блокировки")
    async def blocks_button(message):
        if admin(message): await message.answer(blocked_view()+"\n\nДля ручного управления откройте «🛡 Защита».",reply_markup=main_kb())
    @dp.message(F.text=="📋 События")
    async def events_button(message):
        if not admin(message): return
        try: p=subprocess.run(["journalctl","-u","xfi-guard","-u","xfi-guard-bot","-n","25","--no-pager"],text=True,capture_output=True,timeout=8,check=False); text=(p.stdout or p.stderr).strip()[-2600:] or "Событий нет."
        except Exception as exc: text=f"❌ Не удалось получить события: {type(exc).__name__}: {exc}"
        await message.answer("📋 Последние события\n\n"+text,reply_markup=main_kb())
    @dp.message(F.text=="🤖 AI")
    async def ai_button(message):
        if admin(message): await message.answer("🤖 AI ЦЕНТР\n\nЕдиный консилиум Gemini + Groq + OpenRouter + RouterAI.",reply_markup=ai_center_menu())
    @dp.message(F.text=="⚙️ 3X-UI")
    async def xui_button(message):
        if admin(message): await message.answer("⚙️ 3X-UI\n\nУправление API-подключениями 3X-UI.",reply_markup=__import__("xfi_guard.xui_ui",fromlist=["xui_menu"]).xui_menu())
    @dp.message(F.text=="🔄 Проверка")
    async def check_button(message): await status_command(message)
    @dp.message(F.text=="🔄 Обновить")
    async def update_button(message):
        if admin(message): await message.answer("⏳ Запускаю безопасное обновление XFI Guard..."); subprocess.Popen(["systemctl","start","xfi-guard-update.service"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    @dp.message(F.text=="❓ Помощь")
    async def help_button(message):
        if admin(message): await message.answer("❓ XFI Guard\n\n/start — главное меню\n/status — полный статус\n/blocked — активные блокировки IP\n/vps — состояние подключённых VPS\n/force_update — принудительное обновление\n/threats — рейтинг угроз\n/defense_history — история защиты",reply_markup=main_kb())
    @dp.message(F.text=="⬅️ Главное меню")
    async def back_main(message,state:FSMContext):
        if admin(message): await state.clear(); await message.answer("🏠 Главное меню",reply_markup=main_kb())
    @dp.message()
    async def unknown_message(message):
        if admin(message): await message.answer("Команда не распознана. Нажмите /start.",reply_markup=main_kb())
    return dp

async def vps_view():
    nodes=await asyncio.to_thread(collect_nodes)
    if not nodes: return "🖥 VPS УЗЛЫ\n\nПодключённые узлы не настроены.\n\nДобавьте [[nodes]] в config.toml."
    lines=["🖥 VPS УЗЛЫ", "", f"Всего узлов: {len(nodes)}"]
    for x in nodes:
        icon="🟢" if x.get("status")=="online" else "🔴"; lines += [f"{icon} {x.get('name')} — {x.get('host')}",f"   XFI Guard: {x.get('xfi_guard','—')}",f"   Fail2Ban: {x.get('fail2ban','—')}"]
        if x.get("error"): lines.append(f"   Ошибка: {x['error']}" )
    return "\n".join(lines)[:3900]

async def main():
    token=os.getenv("XFI_GUARD_BOT_TOKEN","").strip()
    if not token: raise RuntimeError("XFI_GUARD_BOT_TOKEN не задан")
    dp=build_dispatcher(); bot=Bot(token=token); print("XFI Guard Bot: polling запущен",flush=True)
    try: await dp.start_polling(bot,allowed_updates=dp.resolve_used_update_types())
    finally: await bot.session.close()
if __name__=="__main__": asyncio.run(main())