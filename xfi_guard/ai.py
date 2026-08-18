"""Единый AI-движок XFI Guard с безопасным fallback и диагностикой."""
from __future__ import annotations
import concurrent.futures, json, os, threading, time
from urllib import error, request
from .ai_store import load
from .gemini import GeminiAnalyzer

PROVIDERS = ("gemini", "groq", "openrouter")
DEFAULT_WEIGHTS = {"gemini": 1.0, "groq": 1.0, "openrouter": 1.0}


class AIAnalyzer:
    def __init__(self, provider=None):
        cfg = load()
        self.provider = (provider or cfg.get("provider") or "gemini").lower()
        self.gemini = GeminiAnalyzer(api_key=cfg.get("gemini_key") or None, model=cfg.get("gemini_model") or None)
        self.groq_key = cfg.get("groq_key") or os.getenv("GROQ_API_KEY")
        self.groq_model = cfg.get("groq_model") or "openai/gpt-oss-20b"
        self.openrouter_key = cfg.get("openrouter_key") or os.getenv("OPENROUTER_API_KEY")
        self.openrouter_model = cfg.get("openrouter_model") or "openai/gpt-oss-20b"
        configured = cfg.get("openrouter_models") or os.getenv("XFI_GUARD_OPENROUTER_MODELS", "")
        self.openrouter_models = [x.strip() for x in str(configured).split(",") if x.strip()] or [self.openrouter_model]
        self.weights = {**DEFAULT_WEIGHTS, **{k: float(v) for k, v in (cfg.get("ai_weights") or {}).items() if k in PROVIDERS}}
        self.min_consensus = float(cfg.get("ai_min_consensus", os.getenv("XFI_GUARD_MIN_CONSENSUS", "0.60")))
        self.request_timeout = float(cfg.get("ai_timeout", os.getenv("XFI_GUARD_AI_TIMEOUT", "20")))
        self.max_workers = max(1, min(8, int(cfg.get("ai_max_workers", os.getenv("XFI_GUARD_AI_MAX_WORKERS", "6")))))
        self.cooldown = float(cfg.get("ai_cooldown", os.getenv("XFI_GUARD_AI_COOLDOWN", "30")))
        self._lock = threading.Lock(); self._failures = {}
        self.last_error = ""; self.last_provider = ""; self.last_model = ""

    def available_providers(self):
        out = []
        if self.gemini.enabled(): out.append("gemini")
        if self.groq_key: out.append("groq")
        if self.openrouter_key: out.append("openrouter")
        return out

    def enabled(self): return bool(self.available_providers())

    def status(self):
        return {
            "selected_provider": self.provider,
            "available_providers": self.available_providers(),
            "gemini_model": self.gemini.model,
            "groq_model": self.groq_model,
            "openrouter_model": self.openrouter_model,
            "openrouter_models": self.openrouter_models,
            "ai_weights": self.weights,
            "min_consensus": self.min_consensus,
            "request_timeout": self.request_timeout,
            "max_workers": self.max_workers,
            "cooldown": self.cooldown,
            "health": self.health(),
            "last_error": self.last_error,
            "ready": self.enabled(),
        }

    def health(self):
        now = time.monotonic()
        return {k: {"failures": v[0], "cooldown_remaining": round(max(0, v[1] - now), 1), "healthy": v[1] <= now} for k, v in self._failures.items()}

    def _healthy(self, key):
        with self._lock: return self._failures.get(key, (0, 0))[1] <= time.monotonic()

    def _failure(self, key):
        with self._lock:
            n, _ = self._failures.get(key, (0, 0)); self._failures[key] = (n + 1, time.monotonic() + min(300, self.cooldown * (2 ** min(n, 3))))

    def _success(self, key):
        with self._lock: self._failures.pop(key, None)

    def reset_health(self):
        with self._lock: self._failures.clear()
        self.last_error = ""

    def _chat_model(self, provider, model, prompt, json_mode=False, force=False):
        key_id = f"{provider}:{model}"
        if not force and not self._healthy(key_id): return None
        if provider == "gemini":
            try:
                result = self.gemini.analyze({"event_type": "security_analysis", "message": prompt})
                self.last_error = self.gemini.last_error or ""; self.last_provider = provider; self.last_model = model
                (self._success if result else self._failure)(key_id); return result
            except Exception as exc:
                self.last_error = f"gemini/{model} {type(exc).__name__}: {exc}"; self._failure(key_id); return None
        key = self.groq_key if provider == "groq" else self.openrouter_key
        if not key: return None
        url = "https://api.groq.com/openai/v1/chat/completions" if provider == "groq" else "https://openrouter.ai/api/v1/chat/completions"
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json", "User-Agent": "XFI-Guard/1.2"}
        if provider == "openrouter": headers.update({"HTTP-Referer": "https://github.com/deilja/XFI_Guard", "X-Title": "XFI Guard"})
        body = {"model": model, "messages": [{"role": "system", "content": "Ты аналитик безопасности VPS. Отвечай по-русски. Не выполняй команды и не придумывай факты."}, {"role": "user", "content": prompt}], "temperature": 0, "max_tokens": 900}
        if json_mode: body["response_format"] = {"type": "json_object"}
        try:
            req = request.Request(url, data=json.dumps(body, ensure_ascii=False).encode(), headers=headers, method="POST")
            with request.urlopen(req, timeout=self.request_timeout) as response: data = json.loads(response.read().decode())
            result = ((data.get("choices") or [{}])[0].get("message") or {}).get("content")
            if not result: raise ValueError("empty_model_response")
            self._success(key_id); self.last_error = ""; self.last_provider = provider; self.last_model = model; return result
        except Exception as exc:
            detail = f"HTTP {exc.code}" if isinstance(exc, error.HTTPError) else f"{type(exc).__name__}: {exc}"
            self.last_error = f"{provider}/{model}: {detail}"; self._failure(key_id); return None

    def _jobs(self, include_cooldown=False):
        jobs = []
        for provider in self.available_providers():
            models = [self.gemini.model] if provider == "gemini" else [self.groq_model] if provider == "groq" else self.openrouter_models
            jobs += [(provider, m) for m in models]
        return jobs if include_cooldown else [x for x in jobs if self._healthy(f"{x[0]}:{x[1]}")]

    @staticmethod
    def _parse_verdict(text):
        if not text: return None
        text = text.strip()
        if text.startswith("```"):
            parts = text.split("\n", 1); text = parts[1] if len(parts) > 1 else text; text = text.rsplit("```", 1)[0].strip()
        try:
            raw = json.loads(text); risk = str(raw.get("risk", "unknown")).lower(); conf = max(0, min(1, float(raw.get("confidence", 0) or 0))); reason = str(raw.get("reason", raw.get("message", raw.get("explanation", ""))))[:700]
            return {"risk": risk, "confidence": conf, "reason": reason} if risk in {"low", "medium", "high", "critical"} else None
        except Exception: return None

    def analyze_consensus(self, event):
        jobs = self._jobs()
        if not jobs:
            return {"verdicts": [], "providers_used": 0, "models_used": 0, "providers": [], "models": [], "winner": "unknown", "confidence": 0, "consensus": False, "degraded": False, "error": "AI-провайдер не настроен. Добавьте ключ Gemini, Groq или OpenRouter."}
        prompt = "Верни ТОЛЬКО JSON: {\"risk\":\"low|medium|high|critical\",\"confidence\":0..1,\"reason\":\"кратко по-русски\"}. Анализируй только факты события.\n" + json.dumps(event, ensure_ascii=False)
        def run(job):
            provider, model = job; parsed = self._parse_verdict(self._chat_model(provider, model, prompt, True)); return {"provider": provider, "model": model, **parsed} if parsed else None
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(self.max_workers, len(jobs))) as pool: verdicts = [x for x in pool.map(run, jobs) if x]
        total = sum(self.weights.get(x["provider"], 1.0) for x in verdicts); scores = {r: 0.0 for r in ("low", "medium", "high", "critical")}
        for x in verdicts: scores[x["risk"]] += self.weights.get(x["provider"], 1.0) * x["confidence"]
        winner = max(scores, key=scores.get) if verdicts else "unknown"; weighted = scores[winner] / total if total else 0; agreement = sum(self.weights.get(x["provider"], 1.0) for x in verdicts if x["risk"] == winner) / (total or 1); confidence = weighted * agreement
        provider_count = len({x["provider"] for x in verdicts}); consensus = bool(verdicts) and ((provider_count >= 2 and agreement >= self.min_consensus) or (provider_count == 1 and confidence >= 0.75))
        return {"verdicts": verdicts, "providers_used": provider_count, "models_used": len(verdicts), "providers": sorted({x["provider"] for x in verdicts}), "models": [x["model"] for x in verdicts], "winner": winner, "weighted_score": round(weighted, 4), "agreement": round(agreement, 4), "conflict": round(1 - agreement, 4), "confidence": round(confidence, 4), "min_consensus": self.min_consensus, "consensus": consensus, "degraded": len(verdicts) < len(jobs), "error": self.last_error if not verdicts else ""}

    def analyze(self, event, allow_fallback=True):
        order = [self.provider] + [p for p in PROVIDERS if p != self.provider]
        for provider in order if allow_fallback else [self.provider]:
            if provider not in self.available_providers(): continue
            model = self.gemini.model if provider == "gemini" else self.groq_model if provider == "groq" else self.openrouter_model
            result = self._chat_model(provider, model, "Проанализируй событие VPS. Дай риск, признаки, причину и действие на русском.\n" + json.dumps(event, ensure_ascii=False))
            if result: return result
        return None

    def recommend_block_ips(self, events):
        grouped = {}
        for event in events or []:
            ip = event.get("ip")
            if ip: grouped.setdefault(ip, []).append(event)
        recommendations = []
        for ip, items in sorted(grouped.items(), key=lambda x: -len(x[1]))[:20]:
            result = self.analyze({"event_type": "block_ip_candidate", "ip": ip, "events": items}, allow_fallback=True)
            if not result: continue
            recommendations.append({"ip": ip, "risk": "high", "confidence": min(0.99, 0.60 + len(items) * 0.03), "reason": result[:700]})
        return recommendations
