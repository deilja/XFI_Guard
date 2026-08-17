"""Telegram admin bot for XFI Guard. Интерфейс бота на русском языке."""
from __future__ import annotations
import asyncio, json, os, ipaddress
from urllib import request
from .ai import AIAnalyzer
from .ai_store import load as load_ai, save as save_ai
from .checks import collect_basic_checks
from .events import parse_file
from .attack_surface import collect_attack_surface
from .security import collect_security_checks
from .security_center import ai_report, summarize
from .vpn import collect_vpn_checks
from .firewall import block_ip, unblock_ip, list_blocked_ips, validate_public_ip
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

TOKEN=os.getenv("XFI_GUARD_BOT_TOKEN")
ADMIN_IDS={int(v) for v in os.getenv("XFI_GUARD_ADMIN_IDS","").split(",") if v.strip().isdigit()}
GROQ_MODELS=[("🧠 GPT-OSS 120B","openai/gpt-oss-120b"),("🧠 GPT-OSS 20B","openai/gpt-oss-20b"),("🦙 Llama 3.3 70B","llama-3.3-70b-versatile"),("⚡ Llama 3.1 8B","llama-3.1-8b-instant"),("🌐 Groq Compound","groq/compound"),("🚀 Groq Compound Mini","groq/compound-mini")]

class SetupStates(StatesGroup):
    provider=State(); gemini_key=State(); groq_key=State(); gemini_model=State(); groq_model=State(); block_ip=State(); confirm_block=State(); unblock_ip=State()

def admin(m): return bool(m.from_user and m.from_user.id in ADMIN_IDS)
def mask(k): return k[:4]+"…"+k[-4:] if len(k)>=8 else ("настроен" if k else "не настроен")
def kb(rows): return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=x) for x in row] for row in rows],resize_keyboard=True,is_persistent=True)
def main_kb(): return kb([["📊 Статус","🔐 Безопасность"],["🛡 Fail2Ban","🔥 UFW"],["🌐 VPN/Xray","📋 События"],["🛡 Картина атак","🤖 AI"],["🧠 Центр AI","🚫 Блокировка IP"],["🔄 Проверить сейчас","❓ Помощь"]])
def ai_kb(): return kb([["🟢 Gemini","🔵 Groq"],["🔀 Выбрать AI"],["🔑 Ключ Gemini","🔑 Ключ Groq"],["🧠 Модель Gemini","🧠 Модель Groq"],["📋 Модели Groq","✏️ Своя модель Groq"],["🧪 Проверить AI","ℹ️ Статус AI"],["⬅️ Главное меню"]])
def groq_models_kb():
    rows=[ [x[0] for x in GROQ_MODELS[i:i+2]] for i in range(0,len(GROQ_MODELS),2) ]; rows += [["🔄 Получить модели Groq API"],["✏️ Своя модель Groq"],["⬅️ AI"]]; return kb(rows)
def center_kb(): return kb([["📊 Анализ за 24 часа"],["🚨 Топ атакующих IP"],["🤖 AI-анализ сводки"],["🤖 Рекомендации блокировки"],["🔄 Обновить"],["⬅️ Главное меню"]])
def block_kb(): return kb([["🤖 Рекомендации AI"],["📋 Выбрать IP из событий"],["✏️ Ввести IP вручную"],["📋 Заблокированные IP","🔓 Разблокировать IP"],["⬅️ Главное меню"]])
def confirm_kb(): return kb([["✅ Подтвердить блокировку"],["❌ Отмена"]])
def results(r): return "\n".join(f"{getattr(x,'status','unknown').upper()}: {x.name} — {x.message}" for x in r)[:3800] or "Нет данных."
def events():
    from .config import load_config
    c=load_config(); return parse_file(c.ssh_log,"ssh")+parse_file(c.fail2ban_log,"fail2ban")
def event_dicts():
    return [{"timestamp":getattr(e,"timestamp",""),"severity":getattr(e,"severity","unknown"),"event_type":getattr(e,"event_type","unknown"),"ip":getattr(e,"ip",None),"user":getattr(e,"user",None),"message":getattr(e,"message","")} for e in events()]
def attack_surface_text():
    data=collect_attack_surface(); items=data.get("ips",[])
    lines=["🛡 Полная картина атак за текущий период", "", f"Fail2Ban: {data.get('fail2ban_count',0)}", f"UFW DENY/REJECT: {data.get('ufw_count',0)}", f"SSH неудачных входов: {data.get('ssh_count',0)}", f"Уникальных IP: {len(items)}", ""]
    for x in items[:15]:
        lines.append(f"• {x['ip']} — {x['risk']} ({x['risk_score']}/100) | источники: {', '.join(x['sources'])} | событий: {x['events']}")
        if x.get('jails'): lines.append(f"  Jail: {', '.join(x['jails'])}")
        if x.get('reason'): lines.append(f"  Причина: {x['reason'][:180]}")
    return "\n".join(lines)[:3900]
def fetch_groq_models(key):
    req=request.Request("https://api.groq.com/openai/v1/models",headers={"Authorization":f"Bearer {key}","Content-Type":"application/json"})
    with request.urlopen(req,timeout=15) as response: data=json.loads(response.read().decode())
    return sorted({str(x.get("id")) for x in data.get("data",[]) if x.get("id") and not str(x.get("id")).startswith("whisper")})

def build_dispatcher():
    dp=Dispatcher(storage=MemoryStorage())
    @dp.message(Command("start"))
    async def start(m,state):
        await state.clear()
        if admin(m): await m.answer("🛡 XFI Guard\n\nПанель управления сервером. Выберите функцию:",reply_markup=main_kb())
    @dp.message(Command("status"))
    async def status_command(m):
        if admin(m): await m.answer("📊 Статус XFI Guard\n\n"+results(collect_basic_checks()+collect_security_checks()+collect_vpn_checks()),reply_markup=main_kb())
    @dp.message(F.text=="📊 Статус")
    async def status(m):
        if admin(m): await m.answer("📊 Статус XFI Guard\n\n"+results(collect_basic_checks()+collect_security_checks()+collect_vpn_checks()),reply_markup=main_kb())
    @dp.message(F.text=="🔐 Безопасность")
    async def security(m):
        if admin(m): await m.answer("🔐 Безопасность\n\n"+results(collect_security_checks()),reply_markup=main_kb())
    @dp.message(Command("security"))
    async def security_command(m):
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
            e=events()[-20:]; t="\n".join(f"{x.severity.upper()} | {x.event_type} | {x.ip or '-'} | {x.user or '-'}" for x in e) or "Нет событий."; await m.answer("📋 Последние события\n\n"+t,reply_markup=main_kb())
    @dp.message(F.text=="🛡 Картина атак")
    async def attack_surface(m):
        if admin(m): await m.answer(attack_surface_text(),reply_markup=main_kb())
    @dp.message(F.text=="🔄 Проверить сейчас")
    async def check(m):
        if admin(m): await m.answer("🔄 Проверка завершена\n\n"+results(collect_basic_checks()+collect_security_checks()+collect_vpn_checks()),reply_markup=main_kb())

    @dp.message(F.text=="🚫 Блокировка IP")
    async def block_menu(m,state):
        if admin(m): await state.clear(); await m.answer("🚫 Управление блокировками IP\n\nИИ видит Fail2Ban + UFW + SSH и только рекомендует адреса. Блокировка выполняется только после вашего подтверждения.",reply_markup=block_kb())
    @dp.message(F.text=="🤖 Рекомендации AI")
    async def ai_recommendations(m,state):
        if not admin(m): return
        await state.clear(); await m.answer("🤖 Анализ полной картины атак: SSH + Fail2Ban + UFW...",reply_markup=block_kb())
        recs=AIAnalyzer().recommend_block_ips(event_dicts())
        if not recs:
            await m.answer("❌ AI не дал рекомендаций. Проверьте AI, SSH-события, Fail2Ban и UFW.",reply_markup=block_kb()); return
        for r in recs:
            await m.answer(f"🚨 Рекомендация AI\n\nIP: {r['ip']}\nРиск: {r.get('risk','medium').upper()}\nУверенность: {r['confidence']:.0%}\nПричина: {r['reason']}",reply_markup=kb([[f"🚫 Заблокировать {r['ip']}"],["⬅️ Главное меню"]]))
    @dp.message(F.text=="📋 Выбрать IP из событий")
    async def choose_event_ip(m,state):
        if not admin(m): return
        counts={}
        for e in events():
            ip=getattr(e,"ip",None)
            if ip:
                try: validate_public_ip(ip)
                except ValueError: continue
                counts[ip]=counts.get(ip,0)+1
        if not counts: await m.answer("Нет публичных IPv4 в событиях.",reply_markup=block_kb()); return
        rows=[[f"🌐 {ip} — {n} событий"] for ip,n in sorted(counts.items(),key=lambda x:x[1],reverse=True)[:20]]
        rows.append(["⬅️ Главное меню"]); await m.answer("📋 Выберите IP для блокировки:",reply_markup=kb(rows))
    @dp.message(F.text.startswith("🌐 "))
    async def event_ip_button(m,state):
        if not admin(m): return
        ip=m.text.split()[1]
        await state.update_data(block_ip=ip,source="events"); await state.set_state(SetupStates.confirm_block)
        await m.answer(f"⚠️ Подтвердите блокировку\n\nIP: {ip}\n\nUFW добавит DENY для этого адреса.",reply_markup=confirm_kb())
    @dp.message(F.text=="Ввести IP")
    async def unused(m): pass
    @dp.message(F.text=="✏️ Ввести IP вручную")
    async def manual_block(m,state):
        if admin(m): await state.set_state(SetupStates.block_ip); await m.answer("Введите публичный IPv4 для блокировки, например 203.0.113.10:",reply_markup=kb([["❌ Отмена"]]))
    @dp.message(SetupStates.block_ip)
    async def receive_block_ip(m,state):
        if not admin(m): return
        if m.text=="❌ Отмена": await state.clear(); await m.answer("Отменено.",reply_markup=block_kb()); return
        try: ip=validate_public_ip(m.text or "")
        except ValueError as exc: await m.answer(f"❌ {exc}"); return
        await state.update_data(block_ip=ip); await state.set_state(SetupStates.confirm_block); await m.answer(f"⚠️ Подтвердите блокировку\n\nIP: {ip}",reply_markup=confirm_kb())
    @dp.message(F.text.startswith("🚫 Заблокировать "))
    async def recommended_block_button(m,state):
        if not admin(m): return
        ip=m.text.removeprefix("🚫 Заблокировать ").strip()
        try: ip=validate_public_ip(ip)
        except ValueError: await m.answer("❌ Некорректный IP.",reply_markup=block_kb()); return
        await state.update_data(block_ip=ip); await state.set_state(SetupStates.confirm_block); await m.answer(f"⚠️ AI рекомендует проверить этот адрес перед блокировкой.\n\nIP: {ip}\n\nБлокировать?",reply_markup=confirm_kb())
    @dp.message(SetupStates.confirm_block, F.text=="✅ Подтвердить блокировку")
    async def confirm_block(m,state):
        if not admin(m): return
        data=await state.get_data(); ip=data.get("block_ip")
        try: ok,msg=block_ip(ip)
        except ValueError as exc: ok,msg=False,str(exc)
        await state.clear(); await m.answer(("✅ " if ok else "❌ ")+msg,reply_markup=block_kb())
    @dp.message(SetupStates.confirm_block, F.text=="❌ Отмена")
    async def cancel_block(m,state):
        await state.clear(); await m.answer("❌ Блокировка отменена.",reply_markup=block_kb())
    @dp.message(F.text=="📋 Заблокированные IP")
    async def blocked(m):
        if not admin(m): return
        ips=list_blocked_ips(); await m.answer("📋 Заблокированные публичные IP:\n\n"+("\n".join(f"• {ip}" for ip in ips) if ips else "Нет адресов."),reply_markup=block_kb())
    @dp.message(F.text=="🔓 Разблокировать IP")
    async def choose_unblock(m,state):
        if not admin(m): return
        ips=list_blocked_ips()
        if not ips: await m.answer("Нет заблокированных публичных IP.",reply_markup=block_kb()); return
        await state.set_state(SetupStates.unblock_ip); await m.answer("Выберите IP для разблокировки:\n\n"+"\n".join(f"🔓 {ip}" for ip in ips),reply_markup=kb([[f"🔓 {ip}"] for ip in ips[:20]]+[["❌ Отмена"]]))
    @dp.message(SetupStates.unblock_ip)
    async def do_unblock(m,state):
        if not admin(m): return
        if m.text=="❌ Отмена": await state.clear(); await m.answer("Отменено.",reply_markup=block_kb()); return
        if not m.text.startswith("🔓 "): return
        ip=m.text[3:].strip()
        try: ok,msg=unblock_ip(ip)
        except ValueError as exc: ok,msg=False,str(exc)
        await state.clear(); await m.answer(("✅ " if ok else "❌ ")+msg,reply_markup=block_kb())

    @dp.message(F.text=="🤖 AI")
    async def ai(m):
        if admin(m):
            c=load_ai(); await m.answer(f"🤖 Центр AI\n\nАктивный провайдер: {c.get('provider','gemini').upper()}\nGemini: {mask(c.get('gemini_key',''))}\nМодель Gemini: {c.get('gemini_model','gemini-2.5-pro')}\nGroq: {mask(c.get('groq_key',''))}\nМодель Groq: {c.get('groq_model','openai/gpt-oss-20b')}",reply_markup=ai_kb())
    @dp.message(F.text=="🧠 Центр AI")
    async def center(m):
        if admin(m): await m.answer("🧠 Центр AI безопасности\n\nВыберите действие:",reply_markup=center_kb())
    @dp.message(F.text.in_({"📊 Анализ за 24 часа","🚨 Топ атакующих IP","🤖 AI-анализ сводки","🤖 Рекомендации блокировки","🔄 Обновить"}))
    async def center_action(m):
        if not admin(m): return
        if m.text=="🤖 Рекомендации блокировки":
            recs=AIAnalyzer().recommend_block_ips(event_dicts())
            if not recs: await m.answer("❌ AI не дал рекомендаций по блокировке.",reply_markup=center_kb()); return
            for r in recs: await m.answer(f"🚨 AI рекомендует:\n{r['ip']}\nРиск: {r.get('risk','medium').upper()}\nУверенность: {r['confidence']:.0%}\nПричина: {r['reason']}",reply_markup=kb([[f"🚫 Заблокировать {r['ip']}"],["⬅️ Главное меню"]]))
            return
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
        if not admin(m): return
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
        if admin(m): await m.answer("Выберите модель Groq:",reply_markup=groq_models_kb())
    @dp.message(F.text.in_({x[0] for x in GROQ_MODELS}))
    async def groq_model_button(m):
        if not admin(m): return
        model=next(v for k,v in GROQ_MODELS if k==m.text); c=load_ai(); c['groq_model']=model; save_ai(c); await m.answer(f"✅ Модель Groq выбрана:\n{model}",reply_markup=ai_kb())
    @dp.message(F.text=="🔄 Получить модели Groq API")
    async def groq_api_models(m):
        if not admin(m): return
        c=load_ai(); key=c.get('groq_key') or os.getenv('GROQ_API_KEY') or os.getenv('XFI_GUARD_GROQ_API_KEY')
        if not key: await m.answer("❌ Сначала добавьте API-ключ Groq.",reply_markup=groq_models_kb()); return
        try: models=fetch_groq_models(key)
        except Exception as exc: await m.answer(f"❌ Ошибка Groq API: {type(exc).__name__}",reply_markup=groq_models_kb()); return
        if not models: await m.answer("❌ Groq API не вернул моделей.",reply_markup=groq_models_kb()); return
        rows=[[f"🔹 {x}" for x in models[i:i+2]] for i in range(0,min(len(models),30),2)]+[["⬅️ AI"]]; await m.answer("📋 Доступные модели Groq API:",reply_markup=kb(rows))
    @dp.message(F.text.startswith("🔹 "))
    async def groq_api_model_button(m):
        if not admin(m): return
        model=m.text[2:].strip(); c=load_ai(); c['groq_model']=model; save_ai(c); await m.answer(f"✅ Модель Groq выбрана:\n{model}",reply_markup=ai_kb())
    @dp.message(F.text=="✏️ Своя модель Groq")
    async def custom_groq_model(m,state):
        if admin(m): await state.set_state(SetupStates.groq_model); await m.answer("Введите точный ID модели Groq, например: openai/gpt-oss-120b")
    async def savemodel(m,state,p):
        if not admin(m): return
        model=(m.text or '').strip()
        if not model or any(ch.isspace() for ch in model): await m.answer("❌ Некорректное название модели."); return
        c=load_ai(); c['groq_model' if p=='groq' else 'gemini_model']=model; save_ai(c); await state.clear(); await m.answer(f"✅ Модель {p.upper()} изменена: {model}",reply_markup=ai_kb())
    @dp.message(SetupStates.groq_model)
    async def sgr(m,state): await savemodel(m,state,'groq')
    @dp.message(SetupStates.gemini_model)
    async def sgm(m,state): await savemodel(m,state,'gemini')
    @dp.message(F.text=="🧪 Проверить AI")
    async def test(m):
        if admin(m):
            a=AIAnalyzer(); r=a.analyze({'event_type':'manual_test','severity':'warning','message':'Тест подключения XFI Guard AI'})
            await m.answer("🧪 Проверка AI\n\n"+(r or f"❌ AI не вернул ответ.\nПричина: {a.last_error or 'неизвестно'}"),reply_markup=ai_kb())
    @dp.message(F.text=="ℹ️ Статус AI")
    async def aist(m):
        if admin(m):
            c=load_ai(); await m.answer(f"ℹ️ Статус AI\n\nПровайдер: {c.get('provider','gemini').upper()}\nGemini: {mask(c.get('gemini_key',''))}\nGroq: {mask(c.get('groq_key',''))}\nМодель Groq: {c.get('groq_model','openai/gpt-oss-20b')}",reply_markup=ai_kb())
    @dp.message(F.text=="⬅️ AI")
    async def back_ai(m,state): await state.clear(); await m.answer("🤖 Центр AI",reply_markup=ai_kb())
    @dp.message(F.text=="⬅️ Главное меню")
    async def back(m,state): await state.clear(); await m.answer("🛡 XFI Guard — главное меню",reply_markup=main_kb())
    @dp.message(F.text=="❓ Помощь")
    async def help(m):
        if admin(m): await m.answer("❓ Все функции доступны через кнопки.\n\nAI: Gemini/Groq, ключи и модели.\nКартина атак: Fail2Ban + UFW + SSH с оценкой риска.\nБлокировка IP: AI-рекомендации, выбор из событий и ручной ввод. Блокировка всегда требует подтверждения.",reply_markup=main_kb())
    return dp

async def main():
    if not TOKEN or not ADMIN_IDS: raise RuntimeError("Не заданы XFI_GUARD_BOT_TOKEN и XFI_GUARD_ADMIN_IDS")
    await build_dispatcher().start_polling(Bot(TOKEN))
if __name__=='__main__': asyncio.run(main())
