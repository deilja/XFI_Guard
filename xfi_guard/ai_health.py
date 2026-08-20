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
        d=json.loads(STATE.read_text(encoding="utf-8")); return d if isinstance(d,dict) else {"providers":{}}
    except (OSError,ValueError): return {"providers":{}}

def _write(d):
    STATE.parent.mkdir(parents=True,exist_ok=True); STATE.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding="utf-8")
    try: STATE.chmod(0o600)
    except OSError: pass

def record(provider,model,ok,latency_ms,error_text=""):
    d=_read(); p=d.setdefault("providers",{}).setdefault(f"{provider}:{model}",{"checks":0,"success":0,"latency_ms":0,"errors":0}); p["checks"]+=1; p["success"]+=int(ok); p["errors"]+=int(not ok); p["latency_ms"]=round(((p["latency_ms"]*(p["checks"]-1))+latency_ms)/p["checks"],1); p["success_rate"]=round(p["success"]/p["checks"],4); p["last_error"]=(error_text or "")[:300]; p["updated_at"]=datetime.now(timezone.utc).isoformat(); _write(d)

def snapshot(): return _read().get("providers",{})

def adapt_weights(min_weight=0.25,max_weight=1.5):
    cfg=load(); current={p:1.0 for p in PROVIDERS}; current.update(cfg.get("ai_weights") or {}); groups={k:[] for k in current}
    for key,val in snapshot().items(): groups.setdefault(key.split(":",1)[0],[]).append(val)
    for provider,items in groups.items():
        if items:
            success=sum(x.get("success_rate",0) for x in items)/len(items); current[provider]=round(max(min_weight,min(max_weight,current.get(provider,1.0)*(0.5+success))),3)
    cfg["ai_weights"]=current; save(cfg); return current

def run_health_check():
    analyzer=AIAnalyzer(); results=[]
    for provider in PROVIDERS:
        if not analyzer._has_key(provider):
            results.append({"provider":provider,"model":"-","ok":False,"latency_ms":0,"error":"API-ключ не настроен"}); continue
        model={"gemini":analyzer.gemini.model,"groq":analyzer.groq_model,"openrouter":analyzer.openrouter_model,"deepseek":analyzer.deepseek_model}[provider]
        started=time.monotonic(); ok=False; err=""
        try:
            checked=analyzer.check_provider(provider,force=True); ok=bool(checked.get("ok")); err=checked.get("error","")
        except Exception as exc: err=f"{type(exc).__name__}: {exc}"
        latency=round((time.monotonic()-started)*1000,1); record(provider,model,ok,latency,err); results.append({"provider":provider,"model":model,"ok":ok,"latency_ms":latency,"error":err})
    return {"results":results,"weights":adapt_weights(),"timestamp":datetime.now(timezone.utc).isoformat()}

if __name__ == "__main__":
    result=run_health_check(); failed=[x for x in result["results"] if not x["ok"] and x.get("error")!="API-ключ не настроен"]; print(json.dumps({"ok":not failed,"failed":len(failed),"weights":result["weights"]},ensure_ascii=False))
