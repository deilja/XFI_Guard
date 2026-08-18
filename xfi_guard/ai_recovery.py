"""AI recovery/status checks for XFI Guard."""
from __future__ import annotations
import time
from .ai import AIAnalyzer

def check_ai() -> dict:
    ai=AIAnalyzer(); jobs=ai._jobs(); results=[]
    for provider,model in jobs:
        started=time.monotonic()
        result=ai._chat_model(provider,model,'Return ONLY JSON: {"risk":"low","confidence":1,"reason":"health"}',True)
        results.append({"provider":provider,"model":model,"ok":bool(result),"latency_ms":round((time.monotonic()-started)*1000,1),"error":ai.last_error if not result else ""})
    return {"ready":any(x["ok"] for x in results),"results":results,"status":ai.status()}
