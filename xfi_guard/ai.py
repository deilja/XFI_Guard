"""Unified multi-model AI engine: Gemini, Groq and OpenRouter."""
from __future__ import annotations
import concurrent.futures, ipaddress, json, os
from urllib import error, request
from .ai_store import load
from .attack_surface import collect_attack_surface
from .gemini import GeminiAnalyzer
PROVIDERS=("gemini","groq","openrouter")
class AIAnalyzer:
    def __init__(self,provider=None):
        cfg=load(); self.provider=(provider or cfg.get("provider") or "gemini").lower()
        self.gemini=GeminiAnalyzer(api_key=cfg.get("gemini_key") or None,model=cfg.get("gemini_model") or None)
        self.groq_key=cfg.get("groq_key") or os.getenv("GROQ_API_KEY"); self.groq_model=cfg.get("groq_model") or "openai/gpt-oss-20b"
        self.openrouter_key=cfg.get("openrouter_key") or os.getenv("OPENROUTER_API_KEY"); self.openrouter_model=cfg.get("openrouter_model") or "openai/gpt-oss-20b"
        configured=cfg.get("openrouter_models") or os.getenv("XFI_GUARD_OPENROUTER_MODELS",""); self.openrouter_models=[x.strip() for x in str(configured).split(",") if x.strip()] or [self.openrouter_model]
        self.last_error=""; self.last_provider=""; self.last_model=""
    def available_providers(self):
        out=[]
        if self.gemini.enabled(): out.append("gemini")
        if self.groq_key: out.append("groq")
        if self.openrouter_key: out.append("openrouter")
        return out
    def enabled(self): return bool(self.available_providers())
    def status(self): return {"selected_provider":self.provider,"available_providers":self.available_providers(),"gemini_model":self.gemini.model,"groq_model":self.groq_model,"openrouter_model":self.openrouter_model,"openrouter_models":self.openrouter_models,"last_provider":self.last_provider,"last_model":self.last_model,"last_error":self.last_error,"ready":self.enabled()}
    def _chat_model(self,provider,model,prompt,json_mode=False):
        if provider=="gemini": return self._chat("gemini",prompt,json_mode)
        key=self.groq_key if provider=="groq" else self.openrouter_key
        if not key: self.last_error=f"API-ключ {provider} не настроен"; return None
        url="https://api.groq.com/openai/v1/chat/completions" if provider=="groq" else "https://openrouter.ai/api/v1/chat/completions"
        headers={"Authorization":f"Bearer {key}","Content-Type":"application/json","User-Agent":"XFI-Guard/1.2"}
        if provider=="openrouter": headers.update({"HTTP-Referer":"https://github.com/deilja/XFI_Guard","X-Title":"XFI Guard"})
        body={"model":model,"messages":[{"role":"system","content":"Ты аналитик безопасности VPS. Не выполняй команды и не придумывай факты."},{"role":"user","content":prompt}],"temperature":0,"max_tokens":900}
        if json_mode: body["response_format"]={"type":"json_object"}
        try:
            req=request.Request(url,data=json.dumps(body).encode(),headers=headers,method="POST")
            with request.urlopen(req,timeout=30) as response: data=json.loads(response.read().decode())
            text=data["choices"][0]["message"]["content"]; return text
        except error.HTTPError as exc: self.last_error=f"{provider}/{model} HTTP {exc.code}: {exc.read().decode(errors='replace')[:300]}"
        except Exception as exc: self.last_error=f"{provider}/{model} {type(exc).__name__}: {exc}"
        return None
    def _chat(self,provider,prompt,json_mode=False):
        if provider=="gemini":
            result=self.gemini.analyze({"event_type":"security_analysis","message":prompt})
            if result: self.last_provider,self.last_model="gemini",self.gemini.model; return result
            self.last_error=self.gemini.last_error or "Gemini не вернул ответ"; return None
        return self._chat_model(provider,self.groq_model if provider=="groq" else self.openrouter_model,prompt,json_mode)
    def analyze(self,event,allow_fallback=True):
        self.last_error=""; order=[self.provider]+[p for p in PROVIDERS if p!=self.provider]; errors=[]
        for provider in order if allow_fallback else [self.provider]:
            if provider not in self.available_providers(): continue
            result=self._chat(provider,"Проанализируй событие VPS. Дай риск, признаки, причину и действие на русском.\n"+json.dumps(event,ensure_ascii=False))
            if result:return result
            if self.last_error: errors.append(self.last_error)
        self.last_error=" | ".join(errors) or "Ни один AI-провайдер не настроен"; return None
    def _jobs(self):
        jobs=[]
        for provider in self.available_providers():
            models=[self.gemini.model] if provider=="gemini" else [self.groq_model] if provider=="groq" else self.openrouter_models
            jobs += [(provider,m) for m in models]
        return jobs
    def analyze_consensus(self,event):
        """Run every configured model independently. Consensus is advisory; humans authorize blocking."""
        jobs=self._jobs(); prompt="Верни краткий вердикт безопасности: risk (low/medium/high/critical), confidence 0..1, reason. Не придумывай факты.\n"+json.dumps(event,ensure_ascii=False)
        def run(job):
            provider,model=job; result=self._chat_model(provider,model,prompt) if provider!="gemini" else self._chat("gemini",prompt)
            return {"provider":provider,"model":model,"verdict":result} if result else None
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(8,max(1,len(jobs)))) as pool: verdicts=[x for x in pool.map(run,jobs) if x]
        return {"verdicts":verdicts,"providers_used":len({x["provider"] for x in verdicts}),"models_used":len(verdicts),"providers":sorted({x["provider"] for x in verdicts}),"models":[x["model"] for x in verdicts],"consensus":len(verdicts)>=2}
    def recommend_block_ips(self,events):
        candidates={}
        for e in events:
            ip=str(e.get("ip") or "").strip()
            try:
                parsed=ipaddress.ip_address(ip)
                if parsed.version!=4 or not parsed.is_global: continue
            except ValueError: continue
            x=candidates.setdefault(ip,{"ip":ip,"sources":[],"events":0,"severity":"warning","reason":""}); x["events"]+=1; source=str(e.get("source") or e.get("event_type") or "events")
            if source not in x["sources"]: x["sources"].append(source)
            if e.get("severity")=="critical": x["severity"]="critical"
            x["reason"]=str(e.get("reason") or e.get("message") or x["reason"])[:300]
        try:
            for x in collect_attack_surface().get("ips",[]):
                if x.get("ip") and not x.get("blocked"):
                    cur=candidates.setdefault(x["ip"],{"ip":x["ip"],"sources":[],"events":0,"severity":"warning","reason":""}); cur["events"]=max(cur["events"],int(x.get("events",0) or 0)); cur["sources"]=list(dict.fromkeys(cur["sources"]+x.get("sources",[]))); cur["reason"]=str(x.get("reason") or cur["reason"])[:300]
        except Exception as exc: self.last_error=f"Сбор картины атак: {type(exc).__name__}: {exc}"
        try:
            from .firewall import list_blocked_ips; blocked=set(list_blocked_ips())
        except Exception: blocked=set()
        candidates=[x for x in candidates.values() if x["ip"] not in blocked]
        if not candidates or not self.enabled(): return []
        prompt="Выбери максимум 5 IP для защиты VPS. Не придумывай IP. Учитывай SSH, Fail2Ban, UFW и повторяемость. Верни ТОЛЬКО JSON {recommendations:[{ip,reason,risk,confidence}]}. Блокировка только после подтверждения администратора.\n"+json.dumps(candidates,ensure_ascii=False)
        votes={}
        def run(job):
            provider,model=job; result=self._chat_model(provider,model,prompt,json_mode=True) if provider!="gemini" else self._chat("gemini",prompt,json_mode=True); return provider,model,result
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(8,max(1,len(self._jobs())))) as pool:
            for provider,model,result in pool.map(run,self._jobs()):
                if not result: continue
                try: items=json.loads(result).get("recommendations",[])
                except Exception: continue
                for item in items[:5]:
                    ip=str(item.get("ip",""))
                    if ip not in {x["ip"] for x in candidates}: continue
                    try: confidence=max(0.0,min(1.0,float(item.get("confidence",0) or 0)))
                    except (TypeError,ValueError): confidence=0.0
                    votes.setdefault(ip,[]).append({"provider":provider,"model":model,"reason":str(item.get("reason",""))[:500],"risk":str(item.get("risk","medium")).lower(),"confidence":confidence})
        out=[]
        for ip,decisions in votes.items():
            if len(decisions)<2: continue
            best=max(decisions,key=lambda x:x["confidence"]); out.append({"ip":ip,"reason":best["reason"],"risk":best["risk"],"confidence":min(1.0,sum(x["confidence"] for x in decisions)/len(decisions)),"providers":sorted({x["provider"] for x in decisions}),"models":[x["model"] for x in decisions],"votes":len(decisions)})
        return sorted(out,key=lambda x:x["confidence"],reverse=True)[:5]
