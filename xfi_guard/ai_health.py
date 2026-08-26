"""AI provider health metrics and adaptive weights for XFI Guard."""
from __future__ import annotations
import json, os, time
from datetime import datetime, timezone
from pathlib import Path
from .ai import AIAnalyzer, PROVIDERS
from .ai_store import load, save
STATE=Path(os.getenv("XFI_GUARD_AI_HEALTH","/var/lib/xfi-guard/ai_health.json"))
def _read():
    try:
        data=json.loads(STATE.read_text(encoding="utf-8")); return data if isinstance(data,dict) else {"providers":{}}
    except (OSError,ValueError): return {"providers":{}}
def _write(data):
    try:
        STATE.parent.mkdir(parents=True,exist_ok=True); STATE.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8"); STATE.chmod(0o600)
    except OSError: pass
def record(provider,model,ok,latency_ms,error_text=""):
    data=_read(); key=f"{provider}:{model or '-'}"; item=data.setdefault("providers",{}).setdefault(key,{"checks":0,"success":0,"latency_ms":0,"errors":0}); item["checks"]+=1; item["success"]+=int(bool(ok)); item["errors"]+=int(not ok); item["latency_ms"]=round(((item["latency_ms"]*(item["checks"]-1))+max(0.0,latency_ms))/item["checks"],1); item["success_rate"]=round(item["success"]/item["checks"],4); item["last_error"]=(error_text or "")[:1000]; item["updated_at"]=datetime.now(timezone.utc).isoformat(); _write(data)
def snapshot(): return _read().get("providers",{})
def adapt_weights(analyzer=None,min_weight=.25,max_weight=1.5):
    cfg=load(); current={p:1.0 for p in PROVIDERS}; current.update(cfg.get("ai_weights") or {}); groups={p:[] for p in PROVIDERS}
    for key,value in snapshot().items():
        provider=key.split(":",1)[0]
        if provider in groups and isinstance(value,dict): groups[provider].append(value)
    live=analyzer.health() if analyzer is not None and hasattr(analyzer,"health") else {}
    for provider in PROVIDERS:
        configured=bool(live.get(provider,{}).get("configured",False)) if live else True; healthy=bool(live.get(provider,{}).get("healthy",True)) if live else True; items=groups[provider]
        if not configured: current[provider]=0.0; continue
        if not healthy: current[provider]=min_weight; continue
        if items:
            success=sum(float(x.get("success_rate",0.0)) for x in items)/len(items); base=float(current.get(provider,1.0)); current[provider]=round(max(min_weight,min(max_weight,base*(.5+success))),3)
        else: current[provider]=round(max(min_weight,min(max_weight,float(current.get(provider,1.0)))),3)
    cfg["ai_weights"]=current; save(cfg); return current
def run_health_check():
    analyzer=AIAnalyzer(); analyzer.reset_health() if hasattr(analyzer,"reset_health") else None
    results=[]; started=time.monotonic()
    # Prefer the stable low-level API so health checks always bypass model cooldowns.
    if hasattr(analyzer,"check_all_providers"):
        checked=analyzer.check_all_providers()
    else: checked=[]
    for provider in PROVIDERS:
        item=next((x for x in checked if x.get("provider")==provider),{})
        configured=bool(provider in (analyzer.available_providers() if hasattr(analyzer,"available_providers") else []))
        if not configured:
            model=getattr(analyzer,f"{provider}_model","") if provider!="gemini" else getattr(getattr(analyzer,"gemini",None),"model",""); ok=False; err="API-ключ не настроен"
        else:
            model=getattr(analyzer,f"{provider}_model","") if provider!="gemini" else getattr(getattr(analyzer,"gemini",None),"model",""); ok=bool(item.get("ok",False)); err=str(item.get("error") or ("проверка API не прошла" if not ok else ""))
        latency=float(item.get("latency_ms",0) or 0); record(provider,model,ok,latency,err); results.append({"provider":provider,"model":model,"ok":ok,"latency_ms":latency,"error":err,"configured":configured})
    weights=adapt_weights(analyzer); return {"results":results,"weights":weights,"elapsed_ms":round((time.monotonic()-started)*1000,1),"health":analyzer.health() if hasattr(analyzer,"health") else {},"timestamp":datetime.now(timezone.utc).isoformat()}
