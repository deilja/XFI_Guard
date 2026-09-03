"""Telegram UI for Auto Defense 2.0 with manual IP firewall controls."""
from __future__ import annotations
import threading,time
from aiogram import F,Dispatcher
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State,StatesGroup
from aiogram.types import KeyboardButton,ReplyKeyboardMarkup,InlineKeyboardButton,InlineKeyboardMarkup
from .admin_auth import authorized
from .auto_defense import confirm_block,confirm_unblock,history
from .attack_surface import collect_attack_surface
from .firewall import list_blocked_ips,validate_public_ip
_ACTION_LOCK=threading.Lock();_ACTIONS={};_ACTION_TTL=30
class DefenseStates(StatesGroup): block_ip=State(); unblock_ip=State()
def _admin(message): return authorized(message)
def _action_once(key):
 now=time.monotonic()
 with _ACTION_LOCK:
  for k,ts in list(_ACTIONS.items()):
   if now-ts>_ACTION_TTL:_ACTIONS.pop(k,None)
  if key in _ACTIONS:return False
  _ACTIONS[key]=now;return True
def _kb(rows): return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=x) for x in row] for row in rows],resize_keyboard=True,is_persistent=True)
def defense_menu(): return _kb([["🔴 Заблокировать IP","🟢 Разблокировать IP"],["📋 Заблокированные IP"],["🚨 Заблокировать все критические"],["🧮 Рейтинг угроз","📜 История защиты"],["🔄 Обновить список","⬅️ Главное меню"]])
def _confirm_keyboard(action,ip): return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Подтвердить",callback_data=f"manual:{action}:{ip}"),InlineKeyboardButton(text="❌ Отмена",callback_data="manual:cancel")]])
def _threat_candidates():
 data=collect_attack_surface();blocked=set(list_blocked_ips());result=[]
 for item in data.get("ips",[]):
  ip=str(item.get("ip","")).strip();risk=str(item.get("risk","")).lower();score=int(item.get("risk_score",0) or 0)
  if ip and ip not in blocked and (risk in {"low","medium","high","critical"} or score>0):result.append(item)
 return sorted(result,key=lambda x:int(x.get("risk_score",0) or 0),reverse=True)
def _critical_candidates(): return [x for x in _threat_candidates() if str(x.get("risk","")).lower()=="critical" or int(x.get("risk_score",0) or 0)>=80]
def _defense_text():
 blocked=list_blocked_ips();critical=_critical_candidates();lines=["🚫 Управление блокировкой IP","",f"🔒 Заблокировано: {len(blocked)}",f"🚨 Критических к блокировке: {len(critical)}",""]
 if blocked: lines.append("🔒 Текущие блокировки:");lines.extend(f"• {ip}" for ip in blocked[:15]);lines.append(f"… ещё {len(blocked)-15}") if len(blocked)>15 else None;lines.append("")
 if critical: lines.append("🚨 Критические угрозы:");lines.extend(f"• {x.get('ip')} — {str(x.get('risk','critical')).upper()} {int(x.get('risk_score',0) or 0)}/100" for x in critical[:15])
 else:lines.append("✅ Критических угроз для блокировки нет.")
 return "\n".join(lines)[:3900]
def _ranking_text(items): return "\n".join(f"{i+1}. {x.get('ip')} — {str(x.get('risk','unknown')).upper()} {int(x.get('risk_score',0) or 0)}/100 | {x.get('events',0)} событий" for i,x in enumerate(items[:20])) or "Активных угроз не обнаружено."
def _ranking_inline(items):
 rows=[]
 if items:
  rows.append([InlineKeyboardButton(text=f"🚨 Заблокировать ВСЕ угрозы ({len(items)})",callback_data="manual:block_all_threats")]);critical=[x for x in items if str(x.get('risk','')).lower()=='critical' or int(x.get('risk_score',0) or 0)>=80]
  if critical:rows.append([InlineKeyboardButton(text=f"🚨 Только критические ({len(critical)})",callback_data="manual:block_all_critical")])
  rows += [[InlineKeyboardButton(text=f"🚫 Заблокировать {x.get('ip')} ({int(x.get('risk_score',0) or 0)}/100)",callback_data=f"manual:block:{x.get('ip')}")] for x in items[:20]]
 rows += [[InlineKeyboardButton(text="🔄 Обновить угрозы",callback_data="manual:refresh_threats")],[InlineKeyboardButton(text="⬅️ Защита",callback_data="manual:back_defense")]];return InlineKeyboardMarkup(inline_keyboard=rows)
def install_defense_handlers(dp:Dispatcher)->None:
 if getattr(dp,'_xfi_defense_ui_installed',False):return
 dp._xfi_defense_ui_installed=True
 @dp.message(F.text=='🚫 Блокировка IP')
 async def defense_ip_menu(m,state):
  if _admin(m):await state.clear();await m.answer(_defense_text(),reply_markup=defense_menu())
 @dp.message(F.text=='🔴 Заблокировать IP')
 async def block_prompt(m,state):
  if _admin(m):await state.set_state(DefenseStates.block_ip);await m.answer('🔴 Введите публичный IPv4 для блокировки.',reply_markup=_kb([['❌ Отмена'],['⬅️ Главное меню']]))
 @dp.message(DefenseStates.block_ip)
 async def block_input(m,state):
  if not _admin(m):return
  value=(m.text or '').strip()
  if value in {'❌ Отмена','⬅️ Главное меню'}:await state.clear();await m.answer(_defense_text(),reply_markup=defense_menu());return
  try:ip=validate_public_ip(value)
  except ValueError as exc:await m.answer(f'❌ {exc}');return
  await state.clear();await m.answer(f'⚠️ Подтвердите блокировку\n\nIP: {ip}',reply_markup=_confirm_keyboard('block',ip))
 @dp.message(F.text=='🟢 Разблокировать IP')
 async def unblock_prompt(m,state):
  if not _admin(m):return
  items=list_blocked_ips();await state.clear()
  if not items:await m.answer(_defense_text(),reply_markup=defense_menu());return
  await m.answer('🟢 Выберите IP для разблокировки:',reply_markup=_kb([[f'🟢 {ip}'] for ip in items[:40]]+[['⬅️ Главное меню']]));await state.set_state(DefenseStates.unblock_ip)
 @dp.message(DefenseStates.unblock_ip)
 async def unblock_input(m,state):
  if not _admin(m):return
  value=(m.text or '').strip()
  if value=='⬅️ Главное меню':await state.clear();await m.answer(_defense_text(),reply_markup=defense_menu());return
  value=value[2:].strip() if value.startswith('🟢 ') else value
  try:ip=validate_public_ip(value)
  except ValueError as exc:await m.answer(f'❌ {exc}');return
  if ip not in list_blocked_ips():await state.clear();await m.answer('❌ Этот IP сейчас не найден среди блокировок.',reply_markup=defense_menu());return
  await state.clear();await m.answer(f'⚠️ Подтвердите снятие блокировки\n\nIP: {ip}',reply_markup=_confirm_keyboard('unblock',ip))
 @dp.message(F.text=='🚨 Заблокировать все критические')
 async def block_all_critical(m,state):
  if not _admin(m):return
  await state.clear();items=_critical_candidates()
  if not items:await m.answer(_defense_text(),reply_markup=defense_menu());return
  preview='\n'.join(f"• {x.get('ip')} — {str(x.get('risk','critical')).upper()} {int(x.get('risk_score',0) or 0)}/100" for x in items[:20])
  await m.answer(f'⚠️ Подтвердите массовую блокировку ({len(items)})\n\n{preview}',reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f'🚨 Заблокировать все ({len(items)})',callback_data='manual:block_all_critical'),InlineKeyboardButton(text='❌ Отмена',callback_data='manual:cancel')]]))
 @dp.message(F.text=='🔄 Обновить список')
 async def refresh_defense(m,state):
  if _admin(m):await state.clear();await m.answer(_defense_text(),reply_markup=defense_menu())
 @dp.callback_query(F.data.startswith('manual:'))
 async def manual_action(callback):
  if not authorized(callback):await callback.answer('Нет доступа',show_alert=True);return
  parts=(callback.data or '').split(':',2)
  if len(parts)<2:await callback.answer('Некорректное действие',show_alert=True);return
  if parts[1]=='cancel':
   await callback.answer('Отменено');
   try: await callback.message.edit_text(_defense_text(),reply_markup=_ranking_inline(_threat_candidates()))
   except Exception: pass
   return
  if parts[1]=='back_defense':
   await callback.answer();
   try: await callback.message.edit_text(_defense_text(),reply_markup=_ranking_inline(_threat_candidates()))
   except Exception: pass
   return
  if parts[1]=='refresh_threats':
   items=_threat_candidates();await callback.answer('Обновлено')
   try:await callback.message.edit_text('🧮 Рейтинг угроз\n\n'+_ranking_text(items),reply_markup=_ranking_inline(items))
   except Exception:pass
   return
  uid=str(callback.from_user.id)
  if parts[1] in {'block_all_threats','block_all_critical'}:
   key=f'{parts[1]}:{uid}'
   if not _action_once(key):await callback.answer('Эта операция уже выполняется',show_alert=True);return
   items=_threat_candidates() if parts[1]=='block_all_threats' else _critical_candidates();ok=0
   for item in items:
    try:
     done,_=confirm_block(str(item.get('ip')),actor=uid,reason=f'Telegram manual {parts[1]}',metadata={'risk_score':item.get('risk_score'),'risk':item.get('risk')});ok+=int(done)
    except (ValueError,OSError):pass
   await callback.answer(f'Заблокировано: {ok}',show_alert=True);return
  if len(parts)!=3:await callback.answer('Некорректный IP',show_alert=True);return
  action,ip=parts[1],parts[2]
  try:ip=validate_public_ip(ip)
  except ValueError:await callback.answer('Некорректный публичный IP',show_alert=True);return
  if action not in {'block','unblock'}:await callback.answer('Недопустимое действие',show_alert=True);return
  if not _action_once(f'{action}:{uid}:{ip}'):await callback.answer('Эта операция уже выполняется',show_alert=True);return
  try:
   ok,msg=confirm_block(ip,actor=uid,reason='Telegram administrator confirmation') if action=='block' else confirm_unblock(ip,actor=uid,reason='Telegram administrator confirmation')
   await callback.answer('Готово' if ok else str(msg)[:180],show_alert=True)
  except (ValueError,OSError):await callback.answer('Операция не выполнена',show_alert=True)
 @dp.message(F.text=='📋 Заблокированные IP')
 async def blocked(m):
  if _admin(m):await m.answer('📋 Заблокированные IP\n\n'+'\n'.join(f'• {x}' for x in list_blocked_ips()[:100]) or 'Нет активных блокировок.',reply_markup=defense_menu())
 @dp.message(F.text=='🧮 Рейтинг угроз')
 async def ranking(m):
  if _admin(m):
   items=_threat_candidates();await m.answer('🧮 Рейтинг угроз\n\n'+_ranking_text(items),reply_markup=_ranking_inline(items))
 @dp.message(F.text=='📜 История защиты')
 async def defense_history(m):
  if not _admin(m):return
  items=history()[-30:];text='\n'.join(f'• {x}' for x in items) if items else 'Нет записей.';await m.answer('📜 История защиты\n\n'+text[:3800],reply_markup=defense_menu())
