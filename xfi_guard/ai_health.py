"""AI provider health metrics, diagnostics and adaptive selection."""
from __future__ import annotations
import json, os, time
from datetime import datetime, timezone
from pathlib import Path
from .ai import AIAnalyzer
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
    cfg=load(); current={"gemini":1.0,"groq":1.0,"openrouter":1.0,**(cfg.get("ai_weights") or {})}; groups={k:[] for k in current}
    for key,val in snapshot().items(): groups.setdefault(key.split(":",1)[0],[]).append(val)
    for provider,items in groups.items():
        if items:
            success=sum(x.get("success_rate",0) for x in items)/len(items); current[provider]=round(max(min_weight,min(max_weight,current.get(provider,1.0)*(0.5+success))),3)
    cfg["ai_weights"]=current; save(cfg); return current

def select_best_provider(results=None):
    """Select the best currently responding provider without changing API keys."""
    results=results if results is not None else []
    candidates=[]
    for item in results:
        if not item.get("ok"): continue
        provider=str(item.get("provider") or "")
        if not provider: continue
        latency=max(float(item.get("latency_ms") or 0),1.0)
        candidates.append((provider,latency))
    if not candidates:
        return None
    weights=load().get("ai_weights") or {}
    by_provider={}
    for provider,latency in candidates:
        score=float(weights.get(provider,1.0))/latency
        by_provider[provider]=max(by_provider.get(provider,0.0),score)
    best=max(by_provider,key=by_provider.get)
    cfg=load(); cfg["provider"]=best; cfg["ai_auto_selected_provider"]=best; cfg["ai_auto_selected_at"]=datetime.now(timezone.utc).isoformat(); save(cfg)
    return best

def run_health_check():
    analyzer=AIAnalyzer(); results=[]
    for provider in analyzer.available_providers():
        models=[analyzer.gemini.model] if provider=="gemini" else [analyzer.groq_model] if provider=="groq" else analyzer.openrouter_models
        for model in models:
            started=time.monotonic(); ok=False; err=""
            try:
                text=analyzer._chat_model(provider,model,'Return ONLY JSON: {"risk":"low","confidence":0.1,"reason":"healthcheck"}',True,force=True); ok=bool(text); err=analyzer.last_error
            except Exception as exc: err=f"{type(exc).__name__}: {exc}"
            latency=round((time.monotonic()-started)*1000,1); record(provider,model,ok,latency,err); results.append({"provider":provider,"model":model,"ok":ok,"latency_ms":latency,"error":err})
    weights=adapt_weights(); recommended=select_best_provider(results)
    return {"results":results,"weights":weights,"recommended_provider":recommended,"timestamp":datetime.now(timezone.utc).isoformat()}

if __name__ == "__main__":
    result=run_health_check(); failed=[x for x in result["results"] if not x["ok"]]; print(json.dumps({"ok":not failed,"failed":len(failed),"recommended_provider":result["recommended_provider"],"weights":result["weights"]},ensure_ascii=False))
