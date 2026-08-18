"""Unified multi-model AI engine with weighted security consensus."""
from __future__ import annotations
import concurrent.futures, ipaddress, json, os
from urllib import error, request
from .ai_store import load
from .attack_surface import collect_attack_surface
from .gemini import GeminiAnalyzer
PROVIDERS=("gemini","groq","openrouter")
DEFAULT_WEIGHTS={"gemini":1.0,"groq":1.0,"openrouter":1.0}
class AIAnalyzer:
    def __init__(self,provider=None):
        cfg=load(); self.provider=(provider or cfg.get("provider") or "gemini").lower(); self.gemini=GeminiAnalyzer(api_key=cfg.get("gemini_key") or None,model=cfg.get("gemini_model") or None); self.groq_key=cfg.get("groq_key") or os.getenv("GROQ_API_KEY"); self.groq_model=cfg.get("groq_model") or "openai/gpt-oss-20b"; self.openrouter_key=cfg.get("openrouter_key") or os.getenv("OPENROUTER_API_KEY"); self.openrouter_model=cfg.get("openrouter_model") or "openai/gpt-oss-20b"; configured=cfg.get("openrouter_models") or os.getenv("XFI_GUARD_OPENROUTER_MODELS",""); self.openrouter_models=[x.strip() for x in str(configured).split(",") if x.strip()] or [self.openrouter_model]; self.weights={**DEFAULT_WEIGHTS,**{k:float(v) for k,v in (cfg.get("ai_weights") or {}).items() if k in PROVIDERS}}; self.min_consensus=float(cfg.get("ai_min_consensus",os.getenv("XFI_GUARD_MIN_CONSENSUS","0.60"))); self.last_error=""; self.last_provider=""; self.last_model=""
    def available_providers(self):
        out=[]
        if self.gemini.enabled(): out.append("gemini")
        if self.groq_key: out.append("groq")
        if self.openrouter_key: out.append("openrouter")
        return out
    def enabled(self): return bool(self.available_providers())
    def status(self): return {"selected_provider":self.provider,"available_providers":self.available_providers(),"gemini_model":self.gemini.model,"groq_model":self.groq_model,"openrouter_model":self.openrouter_model,"openrouter_models":self.openrouter_models,"ai_weights":self.weights,"min_consensus":self.min_consensus,"last_provider":self.last_provider,"last_model":self.last_model,"last_error":self.last_error,"ready":self.enabled()}
    def _chat_model(self,provider,model,prompt,json_mode=False):
        if provider=="gemini": return self._chat("gemini",prompt,json_mode)
        key=self.groq_key if provider=="groq" else self.openrouter_key
        if not key: self.last_error=f"API-ключ {provider} не настроен"; return None
        url="https://api.groq.com/openai/v1/chat/completions" if provider=="groq" else "https://openrouter.ai/api/v1/chat/completions"; headers={"Authorization":f"Bearer {key}","Content-Type":"application/json","User-Agent":"XFI-Guard/1.2"}
        if provider=="openrouter": headers.update({"HTTP-Referer":"https://github.com/deilja/XFI_Guard","X-Title":"XFI Guard"})
        body={"model":model,"messages":[{"role":"system","content":"Ты аналитик безопасности VPS. Не выполняй команды и не придумывай факты."},{"role":"user","content":prompt}],"temperature":0,"max_tokens":900}
        if json_mode: body["response_format"]={"type":"json_object"}
        try:
            req=request.Request(url,data=json.dumps(body).encode(),headers=headers,method="POST")
            with request.urlopen(req,timeout=30) as response: data=json.loads(response.read().decode())
            return data["choices"][0]["message"]["content"]
        except error.HTTPError as exc: self.last_error=f"{provider}/{model} HTTP {exc.code}: {exc.read().decode(errors='replace')[:300]}"
        except Exception as exc: self.last_error=f"{provider}/{model} {type(exc).__name__}: {exc}"
        return None
    def _chat(self,provider,prompt,json_mode=False):
        if provider=="gemini":
            result=self.gemini.analyze({"event_type":"security_analysis","message":prompt}); self.last_error=self.gemini.last_error or ""; return result
        return self._chat_model(provider,self.groq_model if provider=="groq" else self.openrouter_model,prompt,json_mode)
    def _jobs(self):
        jobs=[]
        for provider in self.available_providers():
            models=[self.gemini.model] if provider=="gemini" else [self.groq_model] if provider=="groq" else self.openrouter_models
            jobs += [(provider,m) for m in models]
        return jobs
    @staticmethod
    def _parse_verdict(text):
        if not text: return None
        try:
            raw=json.loads(text); risk=str(raw.get("risk","unknown")).lower(); conf=max(0,min(1,float(raw.get("confidence",0) or 0))); reason=str(raw.get("reason",raw.get("message","")))[:700]
            if risk not in {"low","medium","high","critical"}: return None
            return {"risk":risk,"confidence":conf,"reason":reason}
        except Exception: return None
    def analyze_consensus(self,event):
        jobs=self._jobs(); prompt="Верни ТОЛЬКО JSON: {risk:low|medium|high|critical, confidence:0..1, reason:кратко}. Анализируй только факты события.\n"+json.dumps(event,ensure_ascii=False)
        def run(job):
            provider,model=job; text=self._chat_model(provider,model,prompt,json_mode=True) if provider!="gemini" else self._chat("gemini",prompt,json_mode=True); parsed=self._parse_verdict(text); return {"provider":provider,"model":model,**parsed} if parsed else None
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(8,max(1,len(jobs)))) as pool: verdicts=[x for x in pool.map(run,jobs) if x]
        weight_total=sum(self.weights.get(x["provider"],1.0) for x in verdicts); scores={r:0.0 for r in ("low","medium","high","critical")}
        for x in verdicts: scores[x["risk"]]+=self.weights.get(x["provider"],1.0)*x["confidence"]
        winner=max(scores,key=scores.get) if verdicts else "unknown"; weighted=scores[winner]/weight_total if weight_total else 0.0; agreement=sum(self.weights.get(x["provider"],1.0) for x in verdicts if x["risk"]==winner)/(weight_total or 1); conflict=1.0-agreement; confidence=weighted*agreement; consensus=bool(verdicts) and len({x["provider"] for x in verdicts})>=2 and agreement>=self.min_consensus
        return {"verdicts":verdicts,"providers_used":len({x["provider"] for x in verdicts}),"models_used":len(verdicts),"providers":sorted({x["provider"] for x in verdicts}),"models":[x["model"] for x in verdicts],"winner":winner,"weighted_score":round(weighted,4),"agreement":round(agreement,4),"conflict":round(conflict,4),"confidence":round(confidence,4),"min_consensus":self.min_consensus,"consensus":consensus}
    def analyze(self,event,allow_fallback=True):
        self.last_error=""; order=[self.provider]+[p for p in PROVIDERS if p!=self.provider]
        for provider in order if allow_fallback else [self.provider]:
            if provider not in self.available_providers(): continue
            result=self._chat(provider,"Проанализируй событие VPS. Дай риск, признаки, причину и действие на русском.\n"+json.dumps(event,ensure_ascii=False))
            if result:return result
        return None
