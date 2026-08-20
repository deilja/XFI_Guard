"""Secure Telegram callbacks and AI provider controls."""
from __future__ import annotations
import asyncio, ipaddress, json, os, subprocess, time
from pathlib import Path
from urllib import request
from aiogram import F
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from .ai_decision import get as get_decision
from .auto_defense import confirm_block
from .ai_store import load as load_ai, save as save_ai

STATE_FILE=Path("/var/lib/xfi-guard/security_monitor.json")
_pending={}; CONFIRM_TTL=120
_bulk_pending={}; _bulk_running=set()

class OpenRouterStates(StatesGroup):
    key = State()
    model = State()

def _load():
    try:
        data=json.loads(STATE_FILE.read_text(encoding="utf-8")); return data if isinstance(data,dict) else {"alerts":[]}
    except (OSError,ValueError): return {"alerts":[]}

def _valid_ip(value):
    try:
        ip=ipaddress.ip_address(value); return not(ip.is_loopback or ip.is_multicast or ip.is_unspecified or ip.is_reserved)
    except ValueError: return False

def _mask(key):
    return key[:4] + "…" + key[-4:] if len(key) >= 8 else "настроен"

async def _safe_callback_answer(callback: CallbackQuery, text: str | None = None, *, show_alert: bool = False) -> bool:
    try:
        if text is None: await callback.answer()
        else: await callback.answer(text, show_alert=show_alert)
        return True
    except TelegramBadRequest as exc:
        message = str(exc).lower()
        if "query is too old" in message or "query id is invalid" in message or "response timeout expired" in message: return False
        raise

def _ai_keyboard():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🟢 Gemini"), KeyboardButton(text="🔵 Groq"), KeyboardButton(text="🟣 OpenRouter")],
        [KeyboardButton(text="🔀 Все AI вместе")],
        [KeyboardButton(text="🔑 Ключ Gemini"), KeyboardButton(text="🔑 Ключ Groq")],
        [KeyboardButton(text="🔑 Ключ OpenRouter")],
        [KeyboardButton(text="🧠 Модель Gemini"), KeyboardButton(text="🧠 Модель Groq")],
        [KeyboardButton(text="🧠 Модель OpenRouter")],
        [KeyboardButton(text="🧪 Проверить AI"), KeyboardButton(text="ℹ️ Статус AI")],
        [KeyboardButton(text="⬆️ Обновить XFI Guard")],
        [KeyboardButton(text="⬅️ Главное меню")]], resize_keyboard=True, is_persistent=True)

def _back_ai_keyboard():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="⬅️ AI")]], resize_keyboard=True, is_persistent=True)

def _fetch_openrouter_models(key):
    req=request.Request("https://openrouter.ai/api/v1/models", headers={"Authorization":f"Bearer {key}","Content-Type":"application/json","HTTP-Referer":"https://github.com/deilja/XFI_Guard","X-Title":"XFI Guard"})
    with request.urlopen(req, timeout=15) as response: data=json.loads(response.read().decode())
    models=[]
    for item in data.get("data", []):
        mid=str(item.get("id", "")).strip()
        if mid and "/" in mid: models.append(mid)
    return sorted(set(models))

def _critical_alerts():
    result={}
    for alert in _load().get("alerts",[]):
        ip=str(alert.get("ip","")).strip(); score=int(alert.get("score",0) or 0); risk=str(alert.get("risk","unknown")).lower()
        if ip and _valid_ip(ip) and (risk=="critical" or score>=80):
            old=result.get(ip)
            if old is None or score>int(old.get("score",0) or 0): result[ip]=alert
    return list(result.values())

def register_alert_callbacks(dp,admin_ids):
    @dp.callback_query(F.data.startswith("xfi:block:"))
    async def block_alert(callback:CallbackQuery):
        uid=callback.from_user.id if callback.from_user else 0
        if uid not in admin_ids: await _safe_callback_answer(callback,"Нет доступа",show_alert=True); return
        ip=callback.data.split(":",2)[2].strip()
        if not _valid_ip(ip): await _safe_callback_answer(callback,"Некорректный IP",show_alert=True); return
        alert=next((x for x in reversed(_load().get("alerts",[])) if x.get("ip")==ip),{})
        _pending[uid]=(ip,time.monotonic()+CONFIRM_TTL,alert.get("decision_id"))
        keyboard=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ ПОДТВЕРДИТЬ БЛОКИРОВКУ",callback_data="xfi:confirm")],[InlineKeyboardButton(text="❌ Отмена",callback_data="xfi:cancel")]])
        await _safe_callback_answer(callback); await callback.message.answer(f"⚠️ Подтверждение защиты\n\nIP: {ip}\nDecision ID: {alert.get('decision_id','-')}\n\nПодтверждение действительно 2 минуты.",reply_markup=keyboard)

    @dp.callback_query(F.data=="xfi:block_all_critical")
    async def block_all_critical_alert(callback:CallbackQuery):
        uid=callback.from_user.id if callback.from_user else 0
        if uid not in admin_ids: await _safe_callback_answer(callback,"Нет доступа",show_alert=True); return
        items=_critical_alerts()
        if not items:
            await _safe_callback_answer(callback,"Критических угроз для блокировки нет",show_alert=True); return
        _bulk_pending[uid]=(items,time.monotonic()+CONFIRM_TTL)
        preview="\n".join(f"• {x.get('ip')} — {str(x.get('risk','critical')).upper()} {int(x.get('score',0) or 0)}/100" for x in items[:20])
        if len(items)>20: preview += f"\n… ещё {len(items)-20}"
        keyboard=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"🚨 ПОДТВЕРДИТЬ ВСЕ ({len(items)})",callback_data="xfi:confirm_all_critical")],[InlineKeyboardButton(text="❌ Отмена",callback_data="xfi:cancel_all_critical")]])
        await _safe_callback_answer(callback); await callback.message.answer(f"⚠️ Массовая блокировка критических угроз\n\nБудут обработаны {len(items)} IP:\n\n{preview}\n\nПодтверждение действительно 2 минуты.",reply_markup=keyboard)

    @dp.callback_query(F.data=="xfi:confirm_all_critical")
    async def confirm_all_critical(callback:CallbackQuery):
        uid=callback.from_user.id if callback.from_user else 0
        if uid not in admin_ids: await _safe_callback_answer(callback,"Нет доступа",show_alert=True); return
        pending=_bulk_pending.pop(uid,None)
        if not pending or pending[1]<time.monotonic(): await _safe_callback_answer(callback,"Подтверждение истекло",show_alert=True); return
        if uid in _bulk_running: await _safe_callback_answer(callback,"Массовая блокировка уже выполняется",show_alert=True); return
        _bulk_running.add(uid)
        items=pending[0]; ok_count=0; failed=[]
        try:
            for alert in items:
                ip=str(alert.get("ip","")).strip()
                metadata={"decision_id":alert.get("decision_id"),"alert_id":alert.get("id"),"risk_score":alert.get("score"),"bulk":True}
                try:
                    ok,message=confirm_block(ip,actor=str(uid),reason="Security Monitor critical threats confirmed in Telegram",metadata=metadata)
                    if ok: ok_count+=1
                    else: failed.append(f"{ip}: {message}")
                except (ValueError,OSError) as exc: failed.append(f"{ip}: {exc}")
        finally: _bulk_running.discard(uid)
        await _safe_callback_answer(callback,"Готово" if not failed else "Завершено с ошибками",show_alert=True)
        try: await callback.message.edit_reply_markup(reply_markup=None)
        except Exception: pass
        result=f"🚨 Массовая блокировка завершена\n\nЗаблокировано: {ok_count}\nОшибок: {len(failed)}"
        if failed: result += "\n\n"+"\n".join(f"• {x}" for x in failed[:10])
        await callback.message.answer(result[:3900])

    @dp.callback_query(F.data=="xfi:cancel_all_critical")
    async def cancel_all_critical(callback:CallbackQuery):
        _bulk_pending.pop(callback.from_user.id if callback.from_user else 0,None); await _safe_callback_answer(callback,"Отменено"); await callback.message.edit_reply_markup(reply_markup=None)

    @dp.callback_query(F.data=="xfi:confirm")
    async def confirm_alert(callback:CallbackQuery):
        uid=callback.from_user.id if callback.from_user else 0
        if uid not in admin_ids: await _safe_callback_answer(callback,"Нет доступа",show_alert=True); return
        pending=_pending.pop(uid,None)
        if not pending or pending[1]<time.monotonic(): await _safe_callback_answer(callback,"Подтверждение истекло",show_alert=True); return
        ip,_,decision_id=pending; alert=next((x for x in reversed(_load().get("alerts",[])) if x.get("ip")==ip),{})
        decision_id=decision_id or alert.get("decision_id")
        metadata={"decision_id":decision_id,"alert_id":alert.get("id"),"risk_score":alert.get("score"),"consensus":(alert.get("consensus") or {}).get("consensus"),"providers_used":(alert.get("consensus") or {}).get("providers_used")}
        try: ok,message=confirm_block(ip,actor=str(uid),reason="Security Monitor alert confirmed in Telegram",metadata=metadata)
        except (ValueError,OSError) as exc: ok,message=False,str(exc)
        await _safe_callback_answer(callback,"Заблокировано" if ok else "Ошибка",show_alert=True); await callback.message.edit_reply_markup(reply_markup=None); await callback.message.answer(("🛡 IP заблокирован\n\n" if ok else "❌ Блокировка не выполнена\n\n")+f"{ip}\nDecision ID: {decision_id or '-'}\n{message}")

    @dp.callback_query(F.data=="xfi:cancel")
    async def cancel_alert(callback:CallbackQuery): _pending.pop(callback.from_user.id if callback.from_user else 0,None); await _safe_callback_answer(callback,"Отменено"); await callback.message.edit_reply_markup(reply_markup=None)

    @dp.callback_query(F.data.startswith("xfi:ignore:"))
    async def ignore_alert(callback:CallbackQuery):
        if not callback.from_user or callback.from_user.id not in admin_ids: await _safe_callback_answer(callback,"Нет доступа",show_alert=True); return
        await _safe_callback_answer(callback,"Угроза отмечена как просмотренная"); await callback.message.edit_reply_markup(reply_markup=None)

    @dp.callback_query(F.data.startswith("xfi:detail:"))
    async def detail_alert(callback:CallbackQuery):
        if not callback.from_user or callback.from_user.id not in admin_ids: await _safe_callback_answer(callback,"Нет доступа",show_alert=True); return
        alert_id=callback.data.split(":",2)[2]; alert=next((x for x in reversed(_load().get("alerts",[])) if x.get("id")==alert_id),None)
        if not alert:
            await _safe_callback_answer(callback,"Тревога не найдена",show_alert=True); return
        decision=get_decision(alert.get("decision_id")) if alert.get("decision_id") else None
        await _safe_callback_answer(callback); await callback.message.answer(json.dumps({"alert":alert,"ai_decision":decision},ensure_ascii=False,indent=2)[:3900])

    @dp.message(F.text == "⬆️ Обновить XFI Guard")
    async def manual_update(message, state:FSMContext):
        if not message.from_user or message.from_user.id not in admin_ids: return
        await state.clear()
        try:
            result = await asyncio.to_thread(subprocess.run, ["systemctl", "start", "xfi-guard-update.service"], capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                detail=(result.stderr or result.stdout or "systemctl завершился с ошибкой")[:1800]
                await message.answer(f"❌ Не удалось запустить обновление XFI Guard.\n\n{detail}", reply_markup=_ai_keyboard()); return
            await message.answer("⏳ Обновление XFI Guard запущено.\n\nGitHub → проверка → валидация → перезапуск выполняются автоматически.\nРезультат будет отправлен ботом после завершения.", reply_markup=_ai_keyboard())
        except Exception as exc: await message.answer(f"❌ Ошибка запуска обновления: {type(exc).__name__}: {exc}", reply_markup=_ai_keyboard())

    @dp.message(F.text == "🟣 OpenRouter")
    async def openrouter_provider(message, state:FSMContext):
        if not message.from_user or message.from_user.id not in admin_ids: return
        await state.clear(); cfg=load_ai(); key=cfg.get("openrouter_key") or os.getenv("OPENROUTER_API_KEY","")
        if not key: await message.answer("🟣 OpenRouter не настроен.\n\nСначала нажмите «🔑 Ключ OpenRouter». ", reply_markup=_ai_keyboard()); return
        cfg["provider"]="openrouter"; save_ai(cfg); await message.answer(f"🟣 OpenRouter выбран как основной AI.\n\nКлюч: {_mask(key)}\nМодель: {cfg.get('openrouter_model','openai/gpt-oss-20b')}", reply_markup=_ai_keyboard())

    @dp.message(F.text == "🔑 Ключ OpenRouter")
    async def openrouter_key_start(message, state:FSMContext):
        if not message.from_user or message.from_user.id not in admin_ids: return
        await state.set_state(OpenRouterStates.key); await message.answer("🔑 Введите OpenRouter API-ключ.\n\nКлюч проверяется через OpenRouter и сохраняется локально с правами 0600. Не пересылайте ключ другим людям.", reply_markup=_back_ai_keyboard())

    @dp.message(OpenRouterStates.key)
    async def openrouter_key_save(message, state:FSMContext):
        if not message.from_user or message.from_user.id not in admin_ids: return
        key=(message.text or "").strip()
        if not key or len(key)<20: await message.answer("❌ Ключ выглядит некорректно. Введите OpenRouter API-ключ ещё раз.", reply_markup=_back_ai_keyboard()); return
        try:
            models=await asyncio.to_thread(_fetch_openrouter_models,key)
            if not models: raise ValueError("OpenRouter не вернул доступные модели")
            cfg=load_ai(); cfg["openrouter_key"]=key; cfg["provider"]="openrouter"; cfg["openrouter_models"]=models
            current=cfg.get("openrouter_model") or ""
            if current not in models:
                preferred=[x for x in models if x in {"openai/gpt-oss-20b","openai/gpt-oss-120b","google/gemini-2.5-flash","deepseek/deepseek-chat-v3-0324"}]
                cfg["openrouter_model"]=(preferred[0] if preferred else models[0])
            save_ai(cfg); await state.clear(); await message.answer(f"✅ OpenRouter подключён и выбран.\n\nКлюч: {_mask(key)}\nМодель: {cfg['openrouter_model']}\nДоступных моделей: {len(models)}", reply_markup=_ai_keyboard())
        except Exception as exc: await state.clear(); await message.answer(f"❌ OpenRouter не принял ключ или API недоступен.\n\n{type(exc).__name__}: {exc}", reply_markup=_ai_keyboard())

    @dp.message(F.text == "🧠 Модель OpenRouter")
    async def openrouter_model_menu(message, state:FSMContext):
        if not message.from_user or message.from_user.id not in admin_ids: return
        cfg=load_ai(); models=cfg.get("openrouter_models") or []
        if not models and (cfg.get("openrouter_key") or os.getenv("OPENROUTER_API_KEY")):
            try: models=await asyncio.to_thread(_fetch_openrouter_models,cfg.get("openrouter_key") or os.getenv("OPENROUTER_API_KEY")); cfg["openrouter_models"]=models; save_ai(cfg)
            except Exception as exc: await message.answer(f"❌ Не удалось получить список моделей: {type(exc).__name__}: {exc}", reply_markup=_ai_keyboard()); return
        if not models: await message.answer("🧠 Модель OpenRouter\n\nСначала добавьте ключ OpenRouter.", reply_markup=_ai_keyboard()); return
        models=models[:60]; rows=[[KeyboardButton(text="⬅️ AI")]]+[[KeyboardButton(text=("✅ " if x==cfg.get("openrouter_model") else "")+x)] for x in models]; await state.set_state(OpenRouterStates.model); await message.answer("🧠 Выберите модель OpenRouter:", reply_markup=ReplyKeyboardMarkup(keyboard=rows,resize_keyboard=True,is_persistent=True))

    @dp.message(OpenRouterStates.model)
    async def openrouter_model_save(message, state:FSMContext):
        if not message.from_user or message.from_user.id not in admin_ids: return
        value=(message.text or "").strip().removeprefix("✅ "); cfg=load_ai(); models=cfg.get("openrouter_models") or []
        if value=="⬅️ AI": await state.clear(); await message.answer("🤖 AI",reply_markup=_ai_keyboard()); return
        if value not in models: await message.answer("❌ Такой модели нет в списке."); return
        cfg["openrouter_model"]=value; cfg["provider"]="openrouter"; save_ai(cfg); await state.clear(); await message.answer(f"✅ Модель OpenRouter выбрана:\n{value}", reply_markup=_ai_keyboard())
