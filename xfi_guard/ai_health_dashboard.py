"""Compact Telegram-ready AI health dashboard data."""
from __future__ import annotations
from .ai_health import snapshot
from .ai_store import load

def dashboard_text() -> str:
    cfg=load(); stats=snapshot(); selected=cfg.get("provider","gemini"); auto=cfg.get("ai_auto_selected_provider") or "нет"; lines=["XFI Guard — AI Health","",f"Активный провайдер: {selected}",f"Автовыбор: {auto}",f"Consensus: >= {float(cfg.get('ai_min_consensus',0.60))*100:.0f}%"]
    for key,item in sorted(stats.items()):
        rate=float(item.get("success_rate",0))*100; latency=item.get("latency_ms",0); weight=cfg.get("ai_weights",{}).get(key.split(":",1)[0],1.0); state="HEALTHY" if rate>=95 else "DEGRADED" if rate>=70 else "DOWN"; err=item.get("last_error") or "нет"
        lines.append(f"{state} {key}\n  uptime {rate:.1f}% | {latency} ms | weight {weight}\n  ошибка: {err}")
    if len(lines)==5: lines.append("NO HEALTH-CHECK DATA")
    return "\n".join(lines)

def dashboard_data():
    cfg=load(); return {"providers":snapshot(),"weights":cfg.get("ai_weights",{}),"min_consensus":cfg.get("ai_min_consensus",0.60),"selected_provider":cfg.get("provider","gemini"),"auto_selected_provider":cfg.get("ai_auto_selected_provider")}
