"""Telegram admin bot for XFI Guard. All user-facing messages are in Russian."""
from __future__ import annotations
import asyncio, os
from .ai import AIAnalyzer
from .ai_store import load as load_ai, save as save_ai
from .checks import collect_basic_checks
from .events import parse_file
from .security import collect_security_checks
from .security_center import ai_report, summarize
from .vpn import collect_vpn_checks
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup
TOKEN=os.getenv("XFI_GUARD_BOT_TOKEN")
ADMIN_IDS={int(v) for v in os.getenv("XFI_GUARD_ADMIN_IDS","").split(",") if v.strip().isdigit()}
class SetupStates(StatesGroup):
    provider=State(); gemini_key=State(); groq_key=State(); gemini_model=State(); groq_model=State()
def admin(m): return bool(m.from_user and m.from_user.id in ADMIN_IDS)
def mask(k): return k[:4]+"…"+k[-4:] if len(k)>=8 else ("настроен" if k else "не настроен")
def kb(rows): return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=x) for x in row] for row in rows],resize_keyboard=True,is_persistent=True)
def main_kb(): return kb([["📊 Статус","🔐 Безопасность"],["🛡 Fail2Ban","🔥 UFW"],["🌐 VPN/Xray","📋 События"],["🤖 AI","🧠 Центр AI"],["🔄 Проверить сейчас","❓ Помощь"]])
def ai_kb(): return kb([["🟢 Gemini","🔵 Groq"],["🔀 Выбрать AI"],["🔑 Ключ Gemini","🔑 Ключ Groq"],["🧠 Модель Gemini","🧠 Модель Groq"],["🧪 Проверить AI","ℹ️ Статус AI"],["⬅️ Главное меню"]])
def center_kb(): return kb([["📊 Анализ за 24 часа"],["🚨 Топ атакующих IP"],["🤖 AI-анализ сводки"],["🔄 Обновить"],["⬅️ Главное меню"]])
def results(r): return "\n".join(f"{getattr(x,'status','unknown').upper()}: {x.name} — {x.message}" for x in r)[:3800] or "Нет данных."
def events():
    from .config import load_config
    c=load_config(); return parse_file(c.ssh_log,"ssh")+parse_file(c.fail2ban_log,"fail2ban")
def build_dispatcher():
    dp=Dispatcher(storage=MemoryStorage())
    @dp.message(Command("start"))
    async def start(m,state):
        await state.clear()
        if admin(m): await m.answer("🛡 XFI Guard\n\nПанель управления сервером. Выберите нужную функцию:",reply_markup=main_kb())
    @dp.message(Command("status"));
    async def _dummy(m): pass
    @dp.message(F.text=="📊 Статус")
    async def status(m):
        if admin(m): await m.answer("📊 Статус XFI Guard\n\n"+results(collect_basic_checks()+collect_security_checks()+collect_vpn_checks()),reply_markup=main_kb())
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
        if admin(m):
            e=events()[-15:]; t="\n".join(f"{x.severity.upper()} | {x.event_type} | {x.ip or '-'} | {x.user or '-'}" for x in e) or "Нет событий."; await m.answer("📋 Последние события\n\n"+t,reply_markup=main_kb())
    @dp.message(F.text=="🔄 Проверить сейчас")
    async def check(m):
        if admin(m): await m.answer("🔄 Проверка завершена\n\n"+results(collect_basic_checks()+collect_security_checks()+collect_vpn_checks()),reply_markup=main_kb())
    @dp.message(F.text=="🤖 AI")
    async def ai(m):
        if admin(m):
            c=load_ai(); await m.answer(f"🤖 Центр AI\n\nАктивный провайдер: {c.get('provider','gemini').upper()}\nGemini: {mask(c.get('gemini_key',''))}\nМодель Gemini: {c.get('gemini_model','gemini-2.5-pro')}\nGroq: {mask(c.get('groq_key',''))}\nМодель Groq: {c.get('groq_model','llama-3.3-70b-versatile')}",reply_markup=ai_kb())
    @dp.message(F.text=="🧠 Центр AI")
    async def center(m):
        if admin(m): await m.answer("🧠 Центр AI безопасности\n\nВыберите действие:",reply_markup=center_kb())
    @dp.message(F.text.in_({"📊 Анализ за 24 часа","🚨 Топ атакующих IP","🤖 AI-анализ сводки","🔄 Обновить"}))
    async def center_action(m):
        if not admin(m): return
        s=summarize(events(),24)
        if m.text=="📊 Анализ за 24 часа": t=f"📊 Анализ за 24 часа\n\nСобытий: {s['events']}\nУникальных IP: {s['unique_ips']}\nКритических: {s['critical']}\nПредупреждений: {s['warning']}"
        elif m.text=="🚨 Топ атакующих IP": t="🚨 Топ атакующих IP\n\n"+("\n".join(f"{ip}: {n} событий" for ip,n in s['top_ips']) or "Нет данных.")
        elif m.text=="🤖 AI-анализ сводки": t="🤖 AI-анализ\n\n"+(ai_report(events()) or "AI не настроен или не ответил.")
        else: t=f"🔄 Данные обновлены\n\nСобытий: {s['events']}\nУникальных IP: {s['unique_ips']}"
        await m.answer(t[:3900],reply_markup=center_kb())
    @dp.message(F.text.in_({"🟢 Gemini","🔵 Groq","🔀 Выбрать AI"}))
    async def provider(m,state):
        if not admin(m): return
        if m.text=="🔀 Выбрать AI": await state.set_state(SetupStates.provider); await m.answer("Введите название провайдера: gemini или groq",reply_markup=ai_kb()); return
        p="gemini" if m.text=="🟢 Gemini" else "groq"; c=load_ai(); c['provider']=p; save_ai(c); await m.answer(f"✅ Активный AI: {p.upper()}",reply_markup=ai_kb())
    @dp.message(SetupStates.provider)
    async def provider_text(m,state):
        p=(m.text or '').strip().lower()
        if p not in {'gemini','groq'}: await m.answer("Введите только: gemini или groq"); return
        c=load_ai(); c['provider']=p; save_ai(c); await state.clear(); await m.answer(f"✅ Активный AI: {p.upper()}",reply_markup=ai_kb())
    async def ask(m,state,p):
        if admin(m): await state.set_state(SetupStates.gemini_key if p=='gemini' else SetupStates.groq_key); await m.answer(f"🔑 Отправьте API-ключ {p.upper()} одним сообщением. После сохранения сообщение будет удалено.")
    @dp.message(F.text=="🔑 Ключ Gemini")
    async def gk(m,state): await ask(m,state,'gemini')
    @dp.message(F.text=="🔑 Ключ Groq")
    async def qk(m,state): await ask(m,state,'groq')
    async def savekey(m,state,p):
        if not admin(m): return
        k=(m.text or '').strip()
        if len(k)<20: await m.answer("❌ Ключ слишком короткий или некорректный."); return
        c=load_ai(); c['gemini_key' if p=='gemini' else 'groq_key']=k; save_ai(c); await state.clear()
        try: await m.delete()
        except Exception: pass
        await m.answer(f"✅ Ключ {p.upper()} сохранён.",reply_markup=ai_kb())
    @dp.message(SetupStates.gemini_key)
    async def sg(m,state): await savekey(m,state,'gemini')
    @dp.message(SetupStates.groq_key)
    async def sq(m,state): await savekey(m,state,'groq')
    @dp.message(F.text=="🧠 Модель Gemini")
    async def gm(m,state):
        if admin(m): await state.set_state(SetupStates.gemini_model); await m.answer("Введите название модели Gemini:")
    @dp.message(F.text=="🧠 Модель Groq")
    async def gr(m,state):
        if admin(m): await state.set_state(SetupStates.groq_model); await m.answer("Введите название модели Groq:")
    async def savemodel(m,state,p):
        if not admin(m): return
        model=(m.text or '').strip()
        if not model or any(ch.isspace() for ch in model): await m.answer("❌ Некорректное название модели."); return
        c=load_ai(); c['gemini_model' if p=='gemini' else 'groq_model']=model; save_ai(c); await state.clear(); await m.answer(f"✅ Модель {p.upper()} изменена: {model}",reply_markup=ai_kb())
    @dp.message(SetupStates.gemini_model)
    async def sgm(m,state): await savemodel(m,state,'gemini')
    @dp.message(SetupStates.groq_model)
    async def sgr(m,state): await savemodel(m,state,'groq')
    @dp.message(F.text=="🧪 Проверить AI")
    async def test(m):
        if admin(m):
            r=AIAnalyzer().analyze({'event_type':'manual_test','severity':'warning','message':'Тест подключения XFI Guard AI'})
            await m.answer("🧪 Проверка AI\n\n"+(r or "❌ AI не вернул ответ."),reply_markup=ai_kb())
    @dp.message(F.text=="ℹ️ Статус AI")
    async def aist(m):
        if admin(m):
            c=load_ai(); await m.answer(f"ℹ️ Статус AI\n\nПровайдер: {c.get('provider','gemini').upper()}\nGemini: {mask(c.get('gemini_key',''))}\nGroq: {mask(c.get('groq_key',''))}",reply_markup=ai_kb())
    @dp.message(F.text=="⬅️ Главное меню")
    async def back(m,state): await state.clear(); await m.answer("🛡 XFI Guard — главное меню",reply_markup=main_kb())
    @dp.message(F.text=="❓ Помощь")
    async def help(m):
        if admin(m): await m.answer("❓ Все функции XFI Guard доступны через кнопки.\n\nAI можно переключать между Gemini и Groq, задавать API-ключи и модели.",reply_markup=main_kb())
    return dp
async def main():
    if not TOKEN or not ADMIN_IDS: raise RuntimeError("Не заданы XFI_GUARD_BOT_TOKEN и XFI_GUARD_ADMIN_IDS")
    await build_dispatcher().start_polling(Bot(TOKEN))
if __name__=='__main__': asyncio.run(main())
