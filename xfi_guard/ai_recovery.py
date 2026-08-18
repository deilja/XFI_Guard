"""Active AI health check and recovery diagnostics."""
from __future__ import annotations
import time
from .ai import AIAnalyzer

def check_ai(force=True) -> dict:
    ai=AIAnalyzer(); jobs=ai._jobs(include_cooldown=True); results=[]
    for provider,model in jobs:
        started=time.monotonic()
        result=ai._chat_model(provider,model,'Return ONLY JSON: {"risk":"low","confidence":1,"reason":"health"}',True,force=force)
        results.append({"provider":provider,"model":model,"ok":bool(result),"latency_ms":round((time.monotonic()-started)*1000,1),"error":ai.last_error if not result else ""})
    return {"ready":any(x["ok"] for x in results),"providers_ok":sorted({x["provider"] for x in results if x["ok"]}),"results":results,"status":ai.status()}

def reset_and_check() -> dict:
    ai=AIAnalyzer(); ai.reset_health()
    return check_ai(force=True)
