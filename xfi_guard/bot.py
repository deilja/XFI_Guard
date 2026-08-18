"""Telegram admin bot for XFI Guard. Интерфейс бота на русском языке."""
from __future__ import annotations
import asyncio, ipaddress, json, os, subprocess
from urllib import request
from .ai import AIAnalyzer
from .ai_store import load as load_ai, save as save_ai
from .checks import collect_basic_checks
from .events import parse_file
from .attack_surface import collect_attack_surface
from .security import collect_security_checks
from .security_center import ai_report, summarize
from .security_brain import analyze as brain_analyze
from .security_brain_ui import format_brain_report
from .vpn import collect_vpn_checks
from .firewall import block_ip, unblock_ip, list_blocked_ips, validate_public_ip
from .auto_defense import confirm_block
from .gemini import normalize_model
from .alert_callbacks import register_alert_callbacks
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
TOKEN = os.getenv("XFI_GUARD_BOT_TOKEN")
ADMIN_IDS = {int(v) for v in os.getenv("XFI_GUARD_ADMIN_IDS", "").split(",") if v.strip().isdigit()}
GROQ_MODELS = [("🧠 GPT-OSS 120B", "openai/gpt-oss-120b"), ("🧠 GPT-OSS 20B", "openai/gpt-oss-20b"), ("🦙 Llama 3.3 70B", "llama-3.3-70b-versatile"), ("⚡ Llama 3.1 8B", "llama-3.1-8b-instant"), ("🌐 Groq Compound", "groq/compound"), ("🚀 Groq Compound Mini", "groq/compound-mini")]
GEMINI_MODELS = [("🧠 Gemini 3.1 Pro", "gemini-3.1-pro-preview"), ("⚡ Gemini 3.6 Flash", "gemini-3.6-flash"), ("⚡ Gemini 3.5 Flash", "gemini-3.5-flash"), ("🚀 Gemini 3.5 Flash Lite", "gemini-3.5-flash-lite"), ("⚡ Gemini 3.1 Flash Lite", "gemini-3.1-flash-lite"), ("🌐 Gemini 3 Flash Preview", "gemini-3-flash-preview"), ("🧠 Gemini 2.5 Pro", "gemini-2.5-pro"), ("⚡ Gemini 2.5 Flash", "gemini-2.5-flash")]
class SetupStates(StatesGroup):
    provider=State(); gemini_key=State(); groq_key=State(); openrouter_key=State(); gemini_model=State(); groq_model=State(); openrouter_model=State(); block_ip=State(); confirm_block=State(); unblock_ip=State()
def admin(m): return bool(m.from_user and m.from_user.id in ADMIN_IDS)
def mask(k): return k[:4]+"…"+k[-4:] if len(k)>=8 else ("настроен" if k else "не настроен")
def kb(rows): return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=x) for x in row] for row in rows],resize_keyboard=True,is_persistent=True)
def main_kb(): return kb([["📊 Статус","🔐 Безопасность"],["🛡 Fail2Ban","🔥 UFW"],["🌐 VPN/Xray","📋 События"],["🛡 Картина атак","🤖 AI"],["🧠 Security Brain","🧠 Центр AI"],["🚫 Блокировка IP","🔄 Проверить сейчас"],["❓ Помощь"]])
def ai_kb(): return kb([["🟢 Gemini","🔵 Groq","🟣 OpenRouter"],["🔀 Все AI вместе"],["🔑 Ключ Gemini","🔑 Ключ Groq"],["🔑 Ключ OpenRouter"],["🧠 Модель Gemini","🧠 Модель Groq"],["🧠 Модель OpenRouter"],["🧪 Проверить AI","ℹ️ Статус AI"],["⬅️ Главное меню"]])
def center_kb(): return kb([["📊 Анализ за 24 часа"],["🚨 Топ атакующих IP"],["🤖 AI-анализ сводки"],["🤖 Рекомендации блокировки"],["🔄 Обновить"],["⬅️ Главное меню"]])
def block_kb(): return kb([["🤖 Рекомендации AI"],["📋 Выбрать IP из событий"],["✏️ Ввести IP вручную"],["📋 Заблокированные IP","🔓 Разблокировать IP"],["⬅️ Главное меню"]])
def results(r): return "\n".join(f"{getattr(x,'status','unknown').upper()}: {x.name} — {x.message}" for x in r)[:3800] or "Нет данных."
def events():
    from .config import load_config
    c=load_config(); return parse_file(c.ssh_log,"ssh")+parse_file(c.fail2ban_log,"fail2ban")
def active_events():
    blocked={str(ip).strip() for ip in list_blocked_ips()}; return [e for e in events() if not getattr(e,"ip",None) or str(e.ip).strip() not in blocked]
def event_dicts(): return [{"timestamp":getattr(e,"timestamp",""),"severity":getattr(e,"severity","unknown"),"event_type":getattr(e,"event_type","unknown"),"ip":getattr(e,"ip",None),"user":getattr(e,"user",None),"message":getattr(e,"message","")} for e in active_events()]
def attack_surface_text():
    data=collect_attack_surface(); blocked={str(i).strip() for i in list_blocked_ips()}; items=[x for x in data.get("ips",[]) if str(x.get("ip","")) not in blocked]; lines=["🛡 Полная картина атак за текущий период","",f"Fail2Ban: {data.get('fail2ban_count',0)}",f"UFW DENY/REJECT: {data.get('ufw_count',0)}",f"SSH неудачных входов: {data.get('ssh_count',0)}",f"Уникальных активных IP: {len(items)}",""]
    for x in items[:15]: lines.append(f"• {x['ip']} — {x['risk']} ({x['risk_score']}/100) | источники: {', '.join(x['sources'])} | событий: {x['events']}")
    return "\n".join(lines)[:3900]
def fetch_groq_models(key):
    req=request.Request("https://api.groq.com/openai/v1/models",headers={"Authorization":f"Bearer {key}","Content-Type":"application/json"})
    with request.urlopen(req,timeout=15) as response: data=json.loads(response.read().decode())
    return sorted({str(x.get("id")) for x in data.get("data",[]) if x.get("id") and not str(x.get("id")).startswith("whisper")})
def fetch_gemini_models(key):
    req=request.Request("https://generativelanguage.googleapis.com/v1beta/models",headers={"x-goog-api-key":key,"Content-Type":"application/json"})
    with request.urlopen(req,timeout=15) as response: data=json.loads(response.read().decode())
    return sorted({str(x.get("name","")).removeprefix("models/") for x in data.get("models",[]) if str(x.get("name","")).startswith("models/gemini-") and "generateContent" in (x.get("supportedGenerationMethods",[]) or [])})
def build_dispatcher():
    dp=Dispatcher(storage=MemoryStorage())
    register_alert_callbacks(dp,ADMIN_IDS)
    @dp.callback_query(F.data=="xfi_update")
    async def update_callback(callback):
        if not callback.from_user or callback.from_user.id not in ADMIN_IDS: await callback.answer("Нет доступа",show_alert=True); return
        await callback.answer("Обновление запущено"); subprocess.Popen(["systemctl","start","xfi-guard-update.service"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); await callback.message.answer("⏳ Запущено безопасное обновление XFI Guard.")
    @dp.message(Command("start"))
    async def start(m,state):
        await state.clear()
        if admin(m): await m.answer("🛡 XFI Guard\n\nПанель управления сервером.",reply_markup=main_kb())
    @dp.message(Command("status"))
    async def status_command(m):
        if admin(m): await m.answer("📊 Статус XFI Guard\n\n"+results(collect_basic_checks()+collect_security_checks()+collect_vpn_checks()),reply_markup=main_kb())
    @dp.message(F.text=="📊 Статус")
    async def status(m): await status_command(m)
    @dp.message(F.text=="🔐 Безопасность")
    async def security(m):
        if admin(m): await m.answer("🔐 Безопасность\n\n"+results(collect_security_checks()),reply_markup=main_kb())
    @dp.message(F.text=="🛡 Fail2Ban")
    async def fail2ban(m):
        if admin(m): await m.answer("🛡 Fail2Ban\n\n"+results([x for x in collect_security_checks() if x.name=="fail2ban"]),reply_markup=main_kb())
    @dp.message(F.text=="🔥 UFW")
    async def ufw(m):
        if admin(m): await m.answer("🔥 UFW\n\n"+results([x for x in collect_security_checks() if x.name=="ufw"]),reply_markup=main_kb())
    @dp.message(F.text=="🌐 VPN/Xray")
    async def vpn(m):
        if admin(m): await m.answer("🌐 VPN/Xray\n\n"+results(collect_vpn_checks()),reply_markup=main_kb())
    @dp.message(F.text=="📋 События")
    async def ev(m):
        if admin(m): await m.answer("📋 Последние события\n\n"+(("\n".join(f"{x.severity.upper()} | {x.event_type} | {x.ip or '-'}" for x in active_events()[-20:])) or "Нет активных событий."),reply_markup=main_kb())
    @dp.message(F.text=="🛡 Картина атак")
    async def attack_surface(m):
        if admin(m): await m.answer(attack_surface_text(),reply_markup=main_kb())
    @dp.message(F.text=="🔄 Проверить сейчас")
    async def check(m):
        if admin(m): await m.answer("🔄 Проверка завершена\n\n"+results(collect_basic_checks()+collect_security_checks()+collect_vpn_checks()),reply_markup=main_kb())
    @dp.message(F.text=="🧠 Security Brain")
    async def brain(m,state):
        if not admin(m): return
        await state.clear(); await m.answer("🧠 Запускаю Security Brain: локальный анализ + все доступные AI...",reply_markup=main_kb())
        try: report=await asyncio.to_thread(brain_analyze,10); await m.answer(format_brain_report(report),reply_markup=main_kb())
        except Exception as exc: await m.answer(f"❌ Security Brain: {type(exc).__name__}: {exc}",reply_markup=main_kb())
    @dp.message(F.text=="🚫 Блокировка IP")
    async def block_menu(m,state):
        if admin(m): await state.clear(); await m.answer("🚫 Управление блокировками IP\n\nAI только рекомендует. Блокировка требует подтверждения.",reply_markup=block_kb())
    @dp.message(F.text=="🤖 AI")
    async def ai_menu(m,state):
        if admin(m): await state.clear(); await m.answer("🤖 AI\n\nВыберите провайдера или совместный режим.",reply_markup=ai_kb())
    @dp.message(F.text=="🟣 OpenRouter")
    async def openrouter(m,state):
        if admin(m): await m.answer("🟣 OpenRouter\n\nКлюч: "+mask(load_ai().get("openrouter_key",""))+"\nМодель: "+str(load_ai().get("openrouter_model","openai/gpt-oss-20b")),reply_markup=ai_kb())
    @dp.message(F.text=="🔀 Все AI вместе")
    async def all_ai(m):
        if admin(m):
            s=AIAnalyzer().status(); await m.answer("🔀 Мульти-AI режим\n\n"+"\n".join([f"• {p}: {'готов' if p in s['available_providers'] else 'нет ключа'}" for p in ["gemini","groq","openrouter"]])+f"\n\nМодели:\nGemini: {s['gemini_model']}\nGroq: {s['groq_model']}\nOpenRouter: {s['openrouter_model']}",reply_markup=ai_kb())
    @dp.message(F.text=="ℹ️ Статус AI")
    async def ai_status(m):
        if admin(m): await m.answer("ℹ️ AI Status\n\n"+json.dumps(AIAnalyzer().status(),ensure_ascii=False,indent=2),reply_markup=ai_kb())
    @dp.message(F.text=="🧪 Проверить AI")
    async def ai_test(m):
        if admin(m):
            result=await asyncio.to_thread(AIAnalyzer().analyze_consensus,{"event_type":"health_check","severity":"info","message":"Проверка доступности AI XFI Guard"}); await m.answer("🧪 Проверка AI\n\n"+json.dumps(result,ensure_ascii=False,indent=2)[:3800],reply_markup=ai_kb())
    @dp.message(F.text=="🧠 Центр AI")
    async def ai_center(m,state):
        if admin(m): await state.clear(); await m.answer("🧠 Центр AI",reply_markup=center_kb())
    @dp.message(F.text=="📊 Анализ за 24 часа")
    async def center_summary(m):
        if admin(m): await m.answer("📊 Анализ за 24 часа\n\n"+str(summarize()),reply_markup=center_kb())
    @dp.message(F.text=="🚨 Топ атакующих IP")
    async def center_top(m):
        if admin(m): await m.answer(attack_surface_text(),reply_markup=center_kb())
    @dp.message(F.text=="🤖 AI-анализ сводки")
    async def center_ai(m):
        if admin(m): await m.answer("🤖 AI-анализ\n\n"+(ai_report() or "AI не вернул ответ."),reply_markup=center_kb())
    @dp.message(F.text=="🤖 Рекомендации блокировки")
    async def center_recommend(m,state):
        if admin(m):
            await state.clear(); await m.answer("🤖 Анализ кандидатов...",reply_markup=center_kb()); recs=await asyncio.to_thread(AIAnalyzer().recommend_block_ips,event_dicts()); await m.answer("\n\n".join(f"🚨 {r['ip']} — {r['risk'].upper()} ({r['confidence']:.0%})\n{r['reason']}" for r in recs)[:3900] or "Нет рекомендаций.",reply_markup=block_kb())
    @dp.message(F.text=="🤖 Рекомендации AI")
    async def ai_recommendations(m,state): await center_recommend(m,state)
    @dp.message(F.text=="⬅️ Главное меню")
    async def back_main(m,state):
        if admin(m): await state.clear(); await m.answer("🏠 Главное меню",reply_markup=main_kb())
    @dp.message(F.text=="❓ Помощь")
    async def help_menu(m):
        if admin(m): await m.answer("❓ XFI Guard\n\nSecurity Brain объединяет локальный анализ, Gemini, Groq и OpenRouter. AI не блокирует IP самостоятельно.",reply_markup=main_kb())
    return dp
async def main():
    token=os.getenv("XFI_GUARD_BOT_TOKEN")
    if not token: raise RuntimeError("XFI_GUARD_BOT_TOKEN не задан")
    bot=Bot(token=token); dp=build_dispatcher(); print("XFI Guard Bot: polling запущен",flush=True)
    try: await dp.start_polling(bot)
    finally: await bot.session.close()
if __name__=="__main__": asyncio.run(main())