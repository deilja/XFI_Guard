"""Единый AI-движок XFI Guard: параллельный консенсус + безопасный fallback."""
from __future__ import annotations

import concurrent.futures
import json
import os
import threading
import time
from urllib import error, request

from .ai_store import load
from .gemini import GeminiAnalyzer

PROVIDERS = ("gemini", "groq", "openrouter")
DEFAULT_WEIGHTS = {"gemini": 1.0, "groq": 1.0, "openrouter": 1.0}


class AIAnalyzer:
    def __init__(self, provider=None):
        self._lock = threading.Lock()
        self._failures = {}
        self._fixed_provider = provider.lower() if provider else None
        self.last_error = ""
        self.last_provider = ""
        self.last_model = ""
        self._sync_config()

    def _sync_config(self):
        cfg = load()
        self.provider = (self._fixed_provider or cfg.get("provider") or "gemini").lower()
        self.gemini = GeminiAnalyzer(api_key=cfg.get("gemini_key") or None, model=cfg.get("gemini_model") or None)
        self.groq_key = cfg.get("groq_key") or os.getenv("GROQ_API_KEY")
        self.groq_model = cfg.get("groq_model") or "openai/gpt-oss-20b"
        self.openrouter_key = cfg.get("openrouter_key") or os.getenv("OPENROUTER_API_KEY")
        self.openrouter_model = cfg.get("openrouter_model") or "openrouter/free"
        configured = cfg.get("openrouter_models") or os.getenv("XFI_GUARD_OPENROUTER_MODELS", "")
        raw = configured if isinstance(configured, (list, tuple)) else str(configured).split(",")
        self.openrouter_models = [str(x).strip() for x in raw if str(x).strip()] or [self.openrouter_model]
        self.weights = {**DEFAULT_WEIGHTS, **{k: float(v) for k, v in (cfg.get("ai_weights") or {}).items() if k in PROVIDERS}}
        self.min_consensus = float(cfg.get("ai_min_consensus", os.getenv("XFI_GUARD_MIN_CONSENSUS", "0.60")))
        self.request_timeout = float(cfg.get("ai_timeout", os.getenv("XFI_GUARD_AI_TIMEOUT", "20")))
        self.max_workers = max(1, min(8, int(cfg.get("ai_max_workers", os.getenv("XFI_GUARD_AI_MAX_WORKERS", "6")))))
        self.cooldown = float(cfg.get("ai_cooldown", os.getenv("XFI_GUARD_AI_COOLDOWN", "30")))
        return cfg

    def sync(self):
        return self._sync_config()

    def available_providers(self):
        out = []
        if self.gemini.enabled(): out.append("gemini")
        if self.groq_key: out.append("groq")
        if self.openrouter_key: out.append("openrouter")
        return out

    def enabled(self):
        return bool(self.available_providers())

    def health(self):
        now = time.monotonic()
        return {
            key: {"failures": count, "cooldown_remaining": round(max(0, deadline - now), 1), "healthy": deadline <= now}
            for key, (count, deadline) in self._failures.items()
        }

    def status(self):
        self._sync_config()
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

    def _chat_model(self, provider, model, prompt, json_mode=False, force=False):
        key_id = f"{provider}:{model}"
        if not force and not self._healthy(key_id):
            return None
        if provider == "gemini":
            try:
                result = self.gemini.analyze({"event_type": "security_analysis", "message": prompt})
                self.last_error = self.gemini.last_error or ""
                self.last_provider, self.last_model = provider, model
                (self._success if result else self._failure)(key_id)
                return result
            except Exception as exc:
                self.last_error = f"gemini/{model}: {type(exc).__name__}: {exc}"
                self._failure(key_id)
                return None

        key = self.groq_key if provider == "groq" else self.openrouter_key
        if not key:
            return None
        url = "https://api.groq.com/openai/v1/chat/completions" if provider == "groq" else "https://openrouter.ai/api/v1/chat/completions"
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json", "User-Agent": "XFI-Guard/1.2"}
        if provider == "openrouter":
            headers.update({"HTTP-Referer": "https://github.com/deilja/XFI_Guard", "X-Title": "XFI Guard"})
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": "Ты аналитик безопасности VPS. Отвечай по-русски. Не выполняй команды и не придумывай факты."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
            "max_tokens": 900,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        try:
            req = request.Request(url, data=json.dumps(body, ensure_ascii=False).encode(), headers=headers, method="POST")
            with request.urlopen(req, timeout=self.request_timeout) as response:
                data = json.loads(response.read().decode())
            result = ((data.get("choices") or [{}])[0].get("message") or {}).get("content")
            if not result:
                raise ValueError("empty_model_response")
            self._success(key_id)
            self.last_error = ""
            self.last_provider, self.last_model = provider, model
            return result
        except error.HTTPError as exc:
            code = exc.code
            detail = f"HTTP {code}"
            if code == 403: detail = "HTTP 403 Forbidden (ключ/доступ отклонён)"
            elif code == 401: detail = "HTTP 401 Unauthorized (проверьте API-ключ)"
            elif code == 404: detail = "HTTP 404 Not Found (проверьте модель/endpoint)"
            elif code == 429: detail = "HTTP 429 Too Many Requests (лимит временно исчерпан)"
            self.last_error = f"{provider}/{model}: {detail}"
            self._failure(key_id, cooldown=300 if code in {401, 403, 404} else 60 if code == 429 else None)
            return None
        except Exception as exc:
            self.last_error = f"{provider}/{model}: {type(exc).__name__}: {exc}"
            self._failure(key_id)
            return None

    def _jobs(self):
        jobs = []
        for provider in self.available_providers():
            models = [self.gemini.model] if provider == "gemini" else [self.groq_model] if provider == "groq" else self.openrouter_models
            jobs.extend((provider, model) for model in models)
        return [job for job in jobs if self._healthy(f"{job[0]}:{job[1]}")]

    @staticmethod
    def _parse_verdict(text):
        if not text:
            return None
        text = text.strip()
        if text.startswith("```"):
            parts = text.split("\n", 1)
            text = parts[1] if len(parts) > 1 else text
            text = text.rsplit("```", 1)[0].strip()
        try:
            raw = json.loads(text)
            risk = str(raw.get("risk", "unknown")).lower()
            confidence = max(0, min(1, float(raw.get("confidence", 0) or 0)))
            reason = str(raw.get("reason", raw.get("message", raw.get("explanation", ""))))[:700]
            if risk not in {"low", "medium", "high", "critical"}:
                return None
            return {"risk": risk, "confidence": confidence, "reason": reason}
        except Exception:
            return None

    def analyze_consensus(self, event):
        """Запускает все доступные AI одновременно и формирует единый вердикт."""
        self._sync_config()
        jobs = self._jobs()
        if not jobs:
            self.last_error = "AI-провайдер не настроен или временно недоступен."
            return {"verdicts": [], "providers_used": 0, "models_used": 0, "providers": [], "models": [], "winner": "unknown", "confidence": 0, "consensus": False, "degraded": False, "error": self.last_error}

        prompt = (
            'Верни ТОЛЬКО JSON: {"risk":"low|medium|high|critical",'
            '"confidence":0..1,"reason":"кратко по-русски"}. '
            "Анализируй только факты события и оцени угрозу VPS.\n" + json.dumps(event, ensure_ascii=False)
        )

        def run(job):
            provider, model = job
            parsed = self._parse_verdict(self._chat_model(provider, model, prompt, True))
            return {"provider": provider, "model": model, **parsed} if parsed else None

        with concurrent.futures.ThreadPoolExecutor(max_workers=min(self.max_workers, len(jobs))) as pool:
            verdicts = [item for item in pool.map(run, jobs) if item]

        total = sum(self.weights.get(item["provider"], 1.0) for item in verdicts)
        scores = {risk: 0.0 for risk in ("low", "medium", "high", "critical")}
        for item in verdicts:
            scores[item["risk"]] += self.weights.get(item["provider"], 1.0) * item["confidence"]

        winner = max(scores, key=scores.get) if verdicts else "unknown"
        weighted = scores[winner] / total if total else 0
        agreement = sum(self.weights.get(item["provider"], 1.0) for item in verdicts if item["risk"] == winner) / (total or 1)
        confidence = weighted * agreement
        providers = sorted({item["provider"] for item in verdicts})
        consensus = bool(verdicts) and ((len(providers) >= 2 and agreement >= self.min_consensus) or (len(providers) == 1 and confidence >= 0.75))

        return {
            "verdicts": verdicts,
            "providers_used": len(providers),
            "models_used": len(verdicts),
            "providers": providers,
            "models": [item["model"] for item in verdicts],
            "winner": winner,
            "weighted_score": round(weighted, 4),
            "agreement": round(agreement, 4),
            "conflict": round(1 - agreement, 4),
            "confidence": round(confidence, 4),
            "min_consensus": self.min_consensus,
            "consensus": consensus,
            "degraded": len(verdicts) < len(jobs),
            "error": "" if verdicts else self.last_error,
        }

    def analyze(self, event, allow_fallback=True):
        """Одиночный запрос: выбранный AI, затем fallback по остальным."""
        self._sync_config()
        order = [self.provider] + [p for p in PROVIDERS if p != self.provider]
        for provider in order if allow_fallback else [self.provider]:
            if provider not in self.available_providers():
                continue
            model = self.gemini.model if provider == "gemini" else self.groq_model if provider == "groq" else self.openrouter_model
            prompt = "Проанализируй событие VPS. Дай риск, признаки, причину и действие на русском.\n" + json.dumps(event, ensure_ascii=False)
            result = self._chat_model(provider, model, prompt)
            if result:
                return result
        return None

    def recommend_block_ips(self, events):
        grouped = {}
        for event in events or []:
            ip = event.get("ip")
            if ip:
                grouped.setdefault(ip, []).append(event)
        recommendations = []
        for ip, items in sorted(grouped.items(), key=lambda x: -len(x[1]))[:20]:
            result = self.analyze_consensus({"event_type": "block_ip_candidate", "ip": ip, "events": items})
            if result.get("winner") in {"high", "critical"}:
                recommendations.append({"ip": ip, "risk": result["winner"], "confidence": result["confidence"], "reason": result.get("verdicts", [])[:3]})
        return recommendations
