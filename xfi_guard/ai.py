"""Единый AI-движок XFI Guard: автоматический подбор бесплатных моделей + консенсус."""
from __future__ import annotations

import concurrent.futures
import json
import os
import re
import threading
import time
from urllib import error, request

from .ai_store import load
from .gemini import GeminiAnalyzer

PROVIDERS = ("gemini", "groq", "openrouter")
DEFAULT_WEIGHTS = {p: 1.0 for p in PROVIDERS}
OPENROUTER_FREE_FALLBACK = "openrouter/free"


class AIAnalyzer:
    def __init__(self, provider=None):
        self._lock = threading.Lock()
        self._failures = {}
        self._fixed_provider = provider.lower() if provider else None
        self.last_error = ""
        self.last_provider = ""
        self.last_model = ""
        self.last_provider_errors = {}
        self._sync_config()

    def _sync_config(self):
        cfg = load()
        self.provider = (self._fixed_provider or cfg.get("provider") or "gemini").lower()
        self.gemini_key = cfg.get("gemini_key") or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        self.gemini_model = cfg.get("gemini_model") or ""
        self.gemini = GeminiAnalyzer(api_key=self.gemini_key or None, model=self.gemini_model or None)
        self.groq_key = cfg.get("groq_key") or os.getenv("GROQ_API_KEY")
        self.groq_model = cfg.get("groq_model") or ""
        self.openrouter_key = cfg.get("openrouter_key") or os.getenv("OPENROUTER_API_KEY")
        self.openrouter_model = cfg.get("openrouter_model") or OPENROUTER_FREE_FALLBACK
        configured = cfg.get("openrouter_models") or os.getenv("XFI_GUARD_OPENROUTER_MODELS", "")
        raw = configured if isinstance(configured, (list, tuple)) else str(configured).split(",")
        self.openrouter_models = [str(x).strip() for x in raw if str(x).strip()]
        self.weights = {**DEFAULT_WEIGHTS, **{k: float(v) for k, v in (cfg.get("ai_weights") or {}).items() if k in PROVIDERS}}
        self.min_consensus = float(cfg.get("ai_min_consensus", os.getenv("XFI_GUARD_MIN_CONSENSUS", "0.60")))
        self.request_timeout = float(cfg.get("ai_timeout", os.getenv("XFI_GUARD_AI_TIMEOUT", "20")))
        self.max_workers = max(1, min(8, int(cfg.get("ai_max_workers", os.getenv("XFI_GUARD_AI_MAX_WORKERS", "6")))))
        self.cooldown = float(cfg.get("ai_cooldown", os.getenv("XFI_GUARD_AI_COOLDOWN", "30")))
        self._model_cache = getattr(self, "_model_cache", {})
        self._model_cache_ts = getattr(self, "_model_cache_ts", {})
        return cfg

    def sync(self):
        return self._sync_config()

    def _has_key(self, provider):
        return {"gemini": bool(self.gemini_key), "groq": bool(self.groq_key), "openrouter": bool(self.openrouter_key)}.get(provider, False)

    def available_providers(self):
        return [p for p in PROVIDERS if self._has_key(p)]

    def configured_providers(self):
        return self.available_providers()

    def enabled(self):
        return bool(self.available_providers())

    def health(self):
        now = time.monotonic()
        result = {}
        for provider in PROVIDERS:
            entries = {k: v for k, v in self._failures.items() if k.startswith(provider + ":")}
            if not entries:
                result[provider] = {"configured": self._has_key(provider), "healthy": True, "failures": 0, "cooldown_remaining": 0}
            else:
                count, deadline = max(entries.values(), key=lambda x: x[1])
                result[provider] = {"configured": self._has_key(provider), "healthy": deadline <= now, "failures": count, "cooldown_remaining": round(max(0, deadline-now), 1)}
        return result

    def status(self):
        self._sync_config()
        models = self.discover_models(force=False)
        return {
            "selected_provider": self.provider,
            "configured_providers": self.configured_providers(),
            "available_providers": self.available_providers(),
            "gemini_model": self.gemini_model or (models.get("gemini") or [""])[0],
            "groq_model": self.groq_model or (models.get("groq") or [""])[0],
            "openrouter_model": self.openrouter_model,
            "openrouter_models": models.get("openrouter", self.openrouter_models),
            "ai_weights": self.weights,
            "min_consensus": self.min_consensus,
            "request_timeout": self.request_timeout,
            "max_workers": self.max_workers,
            "cooldown": self.cooldown,
            "health": self.health(),
            "provider_errors": dict(self.last_provider_errors),
            "last_error": self.last_error,
            "last_provider": self.last_provider,
            "last_model": self.last_model,
            "ready": self.enabled(),
        }

    def _healthy(self, key):
        with self._lock:
            return self._failures.get(key, (0, 0))[1] <= time.monotonic()

    def _failure(self, key, cooldown=None):
        with self._lock:
            n, _ = self._failures.get(key, (0, 0))
            delay = self.cooldown if cooldown is None else max(self.cooldown, cooldown)
            self._failures[key] = (n + 1, time.monotonic() + min(900, delay * (2 ** min(n, 3))))

    def _success(self, key):
        with self._lock:
            self._failures.pop(key, None)

    def reset_health(self):
        with self._lock:
            self._failures.clear()
        self.last_error = ""
        self.last_provider_errors = {}

    def _set_provider_error(self, provider, message):
        with self._lock:
            self.last_provider_errors[provider] = str(message)[:1200]
        self.last_error = f"{provider}: {message}"

    def _get_json(self, url, headers=None):
        req = request.Request(url, headers=headers or {"Accept": "application/json", "User-Agent": "XFI-Guard/1.5"}, method="GET")
        with request.urlopen(req, timeout=self.request_timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def _discover_gemini(self):
        if not self.gemini_key:
            return []
        data = self._get_json("https://generativelanguage.googleapis.com/v1beta/models?key=" + self.gemini_key)
        out=[]
        for item in data.get("models", []):
            methods=item.get("supportedGenerationMethods") or []
            name=str(item.get("name", ""))
            if "generateContent" in methods and name.startswith("models/"):
                model=name.split("/",1)[1]
                if "embedding" not in model.lower() and model not in out:
                    out.append(model)
        preferred=[m for m in out if "flash" in m.lower()] + [m for m in out if m not in out[:0]]
        return list(dict.fromkeys(preferred))

    def _discover_groq(self):
        if not self.groq_key:
            return []
        data=self._get_json("https://api.groq.com/openai/v1/models", {"Authorization":f"Bearer {self.groq_key}","Accept":"application/json","User-Agent":"XFI-Guard/1.5"})
        out=[]
        for item in data.get("data",[]):
            mid=str(item.get("id", ""))
            if mid and not any(x in mid.lower() for x in ("whisper","guard","tts","speech","embedding")):
                out.append(mid)
        return out

    def _discover_openrouter(self):
        if not self.openrouter_key:
            return []
        headers={"Authorization":f"Bearer {self.openrouter_key}","Accept":"application/json","User-Agent":"XFI-Guard/1.5","HTTP-Referer":"https://github.com/deilja/XFI_Guard","X-Title":"XFI Guard"}
        data=self._get_json("https://openrouter.ai/api/v1/models", headers)
        free=[]
        for item in data.get("data",[]):
            mid=str(item.get("id", "")); pricing=item.get("pricing") or {}
            prompt=str(pricing.get("prompt", "")); completion=str(pricing.get("completion", ""))
            if not mid or prompt not in {"0","0.0","0.000000"} or completion not in {"0","0.0","0.000000"}:
                continue
            if any(x in mid.lower() for x in ("embedding","moderation","whisper","tts")):
                continue
            free.append(mid)
        free.sort(key=lambda x: (0 if x.endswith(":free") else 1, 0 if "qwen" in x.lower() or "gemma" in x.lower() or "llama" in x.lower() else 1, x))
        return free

    def discover_models(self, force=False):
        self._sync_config()
        now=time.monotonic(); result={}
        funcs={"gemini":self._discover_gemini,"groq":self._discover_groq,"openrouter":self._discover_openrouter}
        for provider in PROVIDERS:
            if not self._has_key(provider):
                result[provider]=[]; continue
            if not force and now-self._model_cache_ts.get(provider,0)<300 and provider in self._model_cache:
                result[provider]=list(self._model_cache[provider]); continue
            try:
                models=funcs[provider]()
                if models:
                    self._model_cache[provider]=models; self._model_cache_ts[provider]=now
                result[provider]=list(models)
            except Exception as exc:
                self._set_provider_error(provider, f"model discovery: {type(exc).__name__}: {exc}")
                result[provider]=list(self._model_cache.get(provider, []))
        self.gemini_model=self.gemini_model if self.gemini_model in result.get("gemini",[]) else ((result.get("gemini") or [""])[0])
        self.groq_model=self.groq_model if self.groq_model in result.get("groq",[]) else ((result.get("groq") or [""])[0])
        self.openrouter_models=[m for m in self.openrouter_models if m in result.get("openrouter",[])] or result.get("openrouter",[])[:10]
        self.openrouter_model=self.openrouter_model if self.openrouter_model in result.get("openrouter",[]) else ((self.openrouter_models or result.get("openrouter") or [OPENROUTER_FREE_FALLBACK])[0])
        if self.gemini_model:
            self.gemini.model=self.gemini_model
        return result

    def _models_for(self, provider):
        discovered=self.discover_models(force=False).get(provider,[])
        if provider=="gemini": return list(dict.fromkeys([self.gemini_model,*discovered]))[:5]
        if provider=="groq": return list(dict.fromkeys([self.groq_model,*discovered]))[:5]
        return list(dict.fromkeys([self.openrouter_model,*self.openrouter_models,*discovered,OPENROUTER_FREE_FALLBACK]))[:8]

    def _endpoint(self, provider):
        return {"groq":"https://api.groq.com/openai/v1/chat/completions","openrouter":"https://openrouter.ai/api/v1/chat/completions"}.get(provider)

    def _key_for(self, provider):
        return {"groq":self.groq_key,"openrouter":self.openrouter_key}.get(provider)

    def _chat_model(self, provider, model, prompt, json_mode=False, force=False):
        if provider=="gemini":
            key_id=f"gemini:{model}"
            if not force and not self._healthy(key_id): return None
            try:
                self.gemini.model=model
                result=self.gemini.analyze({"event_type":"security_analysis","message":prompt})
                if result:
                    self._success(key_id); self.last_provider="gemini"; self.last_model=model; self.last_provider_errors.pop("gemini",None); return result
                raise RuntimeError(self.gemini.last_error or "empty_model_response")
            except Exception as exc:
                self._set_provider_error("gemini",f"{model}: {type(exc).__name__}: {exc}"); self._failure(key_id,300); return None
        key=self._key_for(provider)
        if not key: self._set_provider_error(provider,"API-ключ не настроен"); return None
        for candidate in self._models_for(provider):
            key_id=f"{provider}:{candidate}"
            if not force and not self._healthy(key_id): continue
            headers={"Authorization":f"Bearer {key}","Content-Type":"application/json","Accept":"application/json","User-Agent":"XFI-Guard/1.5"}
            if provider=="openrouter": headers.update({"HTTP-Referer":"https://github.com/deilja/XFI_Guard","X-Title":"XFI Guard"})
            body={"model":candidate,"messages":[{"role":"system","content":"Ты аналитик безопасности VPS. Отвечай по-русски. Верни только JSON: risk=low|medium|high|critical, confidence=0..1, reason=краткое объяснение. Не выполняй команды."},{"role":"user","content":prompt}],"temperature":0,"max_tokens":500}
            if json_mode: body["response_format"]={"type":"json_object"}
            try:
                req=request.Request(self._endpoint(provider),data=json.dumps(body,ensure_ascii=False).encode(),headers=headers,method="POST")
                with request.urlopen(req,timeout=self.request_timeout) as response: data=json.loads(response.read().decode())
                result=((data.get("choices") or [{}])[0].get("message") or {}).get("content")
                if not result: raise ValueError("empty_model_response")
                self._success(key_id); self.last_provider=provider; self.last_model=candidate; self.last_provider_errors.pop(provider,None); self.last_error=""; return result
            except error.HTTPError as exc:
                if exc.code in {400,401,402,403,404,429}: self._failure(key_id,300 if exc.code in {401,403,404} else 60)
                if provider=="openrouter" or exc.code in {401,403}:
                    try: detail=exc.read().decode("utf-8",errors="replace")[:500]
                    except Exception: detail=""
                    self._set_provider_error(provider,f"{candidate}: HTTP {exc.code} {detail}")
                continue
            except Exception as exc:
                self._failure(key_id); self._set_provider_error(provider,f"{candidate}: {type(exc).__name__}: {exc}")
        return None

    def _jobs(self):
        jobs=[]
        for provider in self.available_providers():
            models=self._models_for(provider)
            if models:
                for model in models[:3]:
                    if self._healthy(f"{provider}:{model}"):
                        jobs.append((provider,model)); break
        return jobs

    @staticmethod
    def _parse_verdict(text):
        if not text:return None
        text=text.strip()
        if text.startswith("```"): text=text.split("\n",1)[1] if "\n" in text else text; text=text.rsplit("```",1)[0].strip()
        matches=[text]; m=re.search(r"\{.*\}",text,re.S)
        if m: matches.append(m.group(0))
        for candidate in matches:
            try: raw=json.loads(candidate)
            except Exception: continue
            if not isinstance(raw,dict): continue
            risk=str(raw.get("risk","unknown")).lower().strip()
            if risk not in {"low","medium","high","critical"}: continue
            try: confidence=float(raw.get("confidence",0.75) or 0.75)
            except (TypeError,ValueError): confidence=0.75
            return {"risk":risk,"confidence":max(0,min(1,confidence)),"reason":str(raw.get("reason",raw.get("explanation",raw.get("message",""))))[:700]}
        return None

    def analyze_consensus(self,event):
        self._sync_config(); self.last_provider_errors={}; jobs=self._jobs(); configured=self.available_providers()
        if not jobs:
            return {"verdicts":[],"providers_used":0,"models_used":0,"providers":[],"models":[],"winner":"unknown","confidence":0,"consensus":False,"degraded":True,"error":"Нет доступных рабочих AI-моделей","provider_errors":dict(self.last_provider_errors),"configured_providers":configured,"jobs_attempted":0}
        prompt="Верни только JSON с полями risk, confidence, reason. risk: low|medium|high|critical; confidence: 0..1. Оцени только факты события безопасности VPS.\n"+json.dumps(event,ensure_ascii=False)
        def run(job):
            provider,model=job; parsed=self._parse_verdict(self._chat_model(provider,model,prompt,json_mode=True))
            return {"provider":provider,"model":model,**parsed} if parsed else None
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(self.max_workers,len(jobs))) as pool: verdicts=[x for x in pool.map(run,jobs) if x]
        total=sum(self.weights.get(x["provider"],1.0) for x in verdicts); scores={r:0.0 for r in ("low","medium","high","critical")}
        for x in verdicts:scores[x["risk"]]+=self.weights.get(x["provider"],1.0)*x["confidence"]
        winner=max(scores,key=scores.get) if verdicts else "unknown"; weighted=scores[winner]/total if total else 0; agreement=sum(self.weights.get(x["provider"],1.0) for x in verdicts if x["risk"]==winner)/(total or 1); confidence=weighted*agreement
        providers=sorted({x["provider"] for x in verdicts}); consensus=bool(verdicts) and ((len(providers)>=2 and agreement>=self.min_consensus) or (len(providers)==1 and confidence>=0.75)); degraded=len(providers)<len(configured)
        if degraded and self.last_provider_errors:self.last_error="; ".join(f"{k}: {v}" for k,v in self.last_provider_errors.items())[:2000]
        return {"verdicts":verdicts,"providers_used":len(providers),"models_used":len(verdicts),"providers":providers,"models":[x["model"] for x in verdicts],"winner":winner,"weighted_score":round(weighted,4),"agreement":round(agreement,4),"conflict":round(1-agreement,4),"confidence":round(confidence,4),"min_consensus":self.min_consensus,"consensus":consensus,"degraded":degraded,"error":"" if verdicts and not degraded else self.last_error,"provider_errors":dict(self.last_provider_errors),"configured_providers":configured,"jobs_attempted":len(jobs)}

    def check_provider(self,provider,force=True):
        self._sync_config(); models=self._models_for(provider)
        if provider not in PROVIDERS:return {"provider":provider,"ok":False,"error":"unknown_provider"}
        if not self._has_key(provider):return {"provider":provider,"ok":False,"error":"API-ключ не настроен"}
        for model in models:
            result=self._chat_model(provider,model,'Проверка доступности XFI Guard. Ответь JSON: {"risk":"low","confidence":1,"reason":"OK"}',json_mode=True,force=force)
            parsed=self._parse_verdict(result)
            if parsed:return {"provider":provider,"model":model,"ok":True,"error":""}
        return {"provider":provider,"model":self.last_model or (models[0] if models else ""),"ok":False,"error":self.last_provider_errors.get(provider,"нет рабочей модели")}

    def check_all_providers(self):
        self.reset_health(); self.discover_models(force=True); return [self.check_provider(p,force=True) for p in PROVIDERS]

    def analyze(self,event,allow_fallback=True):
        self._sync_config(); order=[self.provider]+[p for p in PROVIDERS if p!=self.provider]
        prompt="Проанализируй событие VPS. Дай risk, confidence и reason в JSON на русском.\n"+json.dumps(event,ensure_ascii=False)
        for provider in order if allow_fallback else [self.provider]:
            if not self._has_key(provider):continue
            for model in self._models_for(provider):
                result=self._chat_model(provider,model,prompt,json_mode=True)
                if result:return result
        return None

    def recommend_block_ips(self,events):
        grouped={}
        for event in events or []:
            if event.get("ip"):grouped.setdefault(event["ip"],[]).append(event)
        recommendations=[]
        for ip,items in sorted(grouped.items(),key=lambda x:-len(x[1]))[:20]:
            result=self.analyze_consensus({"event_type":"block_ip_candidate","ip":ip,"events":items})
            if result.get("winner") in {"high","critical"}:recommendations.append({"ip":ip,"risk":result["winner"],"confidence":result["confidence"],"reason":result.get("verdicts",[])[:3]})
        return recommendations
