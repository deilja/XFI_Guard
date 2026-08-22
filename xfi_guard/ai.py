"""Единый AI-движок XFI Guard: discovery, health-check и консенсус."""
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
from .routerai import RouterAIAdapter

PROVIDERS = ("gemini", "groq", "openrouter", "routerai")
DEFAULT_WEIGHTS = {p: 1.0 for p in PROVIDERS}
OPENROUTER_FREE_FALLBACK = "openrouter/free"
RISK_SCORE = {"low": 0.25, "medium": 0.5, "high": 0.75, "critical": 1.0}


class AIAnalyzer:
    def __init__(self, provider=None):
        self._lock = threading.Lock()
        self._failures: dict[str, tuple[int, float]] = {}
        self._fixed_provider = provider.lower() if provider else None
        self.last_error = ""
        self.last_provider = ""
        self.last_model = ""
        self.last_provider_errors: dict[str, str] = {}
        self._model_cache: dict[str, list[str]] = {}
        self._model_cache_ts: dict[str, float] = {}
        self._sync_config()

    def _sync_config(self):
        cfg = load()
        self.provider = (self._fixed_provider or cfg.get("provider") or "gemini").lower()
        self.gemini_key = cfg.get("gemini_key") or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
        self.gemini_model = cfg.get("gemini_model") or ""
        self.gemini = GeminiAnalyzer(api_key=self.gemini_key or None, model=self.gemini_model or None)
        self.groq_key = cfg.get("groq_key") or os.getenv("GROQ_API_KEY") or ""
        self.groq_model = cfg.get("groq_model") or ""
        self.openrouter_key = cfg.get("openrouter_key") or os.getenv("OPENROUTER_API_KEY") or ""
        self.openrouter_model = cfg.get("openrouter_model") or OPENROUTER_FREE_FALLBACK
        configured = cfg.get("openrouter_models") or os.getenv("XFI_GUARD_OPENROUTER_MODELS", "")
        raw = configured if isinstance(configured, (list, tuple)) else str(configured).split(",")
        self.openrouter_models = [str(x).strip() for x in raw if str(x).strip()]
        self.routerai_key = cfg.get("routerai_key") or os.getenv("ROUTERAI_API_KEY") or ""
        self.routerai_enabled = bool(cfg.get("routerai_enabled", False))
        # Paid RouterAI models are a fallback after free endpoints by default.
        # Keep this aligned with AISettings.routerai_allow_paid.
        self.routerai_allow_paid = bool(cfg.get("routerai_allow_paid", True))
        self.routerai_model = cfg.get("routerai_model") or ""
        configured = cfg.get("routerai_models") or ()
        raw = configured if isinstance(configured, (list, tuple)) else str(configured).split(",")
        self.routerai_models = [str(x).strip() for x in raw if str(x).strip()]
        self.routerai = RouterAIAdapter(self.routerai_key or None, timeout=float(cfg.get("ai_timeout", os.getenv("XFI_GUARD_AI_TIMEOUT", "20"))))
        self.weights = {**DEFAULT_WEIGHTS, **{k: float(v) for k, v in (cfg.get("ai_weights") or {}).items() if k in PROVIDERS}}
        self.min_consensus = float(cfg.get("ai_min_consensus", os.getenv("XFI_GUARD_MIN_CONSENSUS", "0.60")))
        self.request_timeout = float(cfg.get("ai_timeout", os.getenv("XFI_GUARD_AI_TIMEOUT", "20")))
        self.max_workers = max(1, min(8, int(cfg.get("ai_max_workers", os.getenv("XFI_GUARD_AI_MAX_WORKERS", "6")))))
        self.cooldown = float(cfg.get("ai_cooldown", os.getenv("XFI_GUARD_AI_COOLDOWN", "30")))
        return cfg

    def sync(self):
        return self._sync_config()

    def _has_key(self, provider):
        return {
            "gemini": bool(self.gemini_key),
            "groq": bool(self.groq_key),
            "openrouter": bool(self.openrouter_key),
            "routerai": bool(self.routerai_key) and self.routerai_enabled,
        }.get(provider, False)

    def available_providers(self):
        return [p for p in PROVIDERS if self._has_key(p)]

    def configured_providers(self):
        return self.available_providers()

    def enabled(self):
        return bool(self.available_providers())

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
        req = request.Request(url, headers=headers or {"Accept": "application/json", "User-Agent": "XFI-Guard/1.6"}, method="GET")
        with request.urlopen(req, timeout=self.request_timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def _discover_gemini(self):
        if not self.gemini_key:
            return []
        data = self._get_json("https://generativelanguage.googleapis.com/v1beta/models?key=" + self.gemini_key)
        out = []
        for item in data.get("models", []):
            methods = item.get("supportedGenerationMethods") or []
            name = str(item.get("name", ""))
            if "generateContent" not in methods or not name.startswith("models/"):
                continue
            model = name.split("/", 1)[1]
            if "embedding" not in model.lower() and "tts" not in model.lower() and model not in out:
                out.append(model)
        preferred = [m for m in out if "flash" in m.lower()]
        return list(dict.fromkeys(preferred + out))

    def _discover_groq(self):
        if not self.groq_key:
            return []
        data = self._get_json("https://api.groq.com/openai/v1/models", {"Authorization": f"Bearer {self.groq_key}", "Accept": "application/json", "User-Agent": "XFI-Guard/1.6"})
        out = []
        for item in data.get("data", []):
            mid = str(item.get("id", ""))
            if mid and not any(x in mid.lower() for x in ("whisper", "guard", "tts", "speech", "embedding")):
                out.append(mid)
        return out

    def _discover_openrouter(self):
        if not self.openrouter_key:
            return []
        headers = {"Authorization": f"Bearer {self.openrouter_key}", "Accept": "application/json", "User-Agent": "XFI-Guard/1.6", "HTTP-Referer": "https://github.com/deilja/XFI_Guard", "X-Title": "XFI Guard"}
        data = self._get_json("https://openrouter.ai/api/v1/models", headers)
        free = []
        for item in data.get("data", []):
            mid = str(item.get("id", ""))
            pricing = item.get("pricing") or {}
            if not mid or float(pricing.get("prompt") or 1) != 0 or float(pricing.get("completion") or 1) != 0:
                continue
            if any(x in mid.lower() for x in ("embedding", "moderation", "whisper", "tts")):
                continue
            free.append(mid)
        free.sort(key=lambda x: (0 if x.endswith(":free") else 1, 0 if any(k in x.lower() for k in ("qwen", "gemma", "llama", "glm")) else 1, x))
        return free

    def _discover_routerai(self):
        if not self.routerai_key or not self.routerai_enabled:
            return []
        if self.routerai_allow_paid:
            return self.routerai.models()
        return self.routerai.free_models()

    def discover_models(self, force=False):
        self._sync_config()
        now = time.monotonic()
        result = {}
        funcs = {"gemini": self._discover_gemini, "groq": self._discover_groq, "openrouter": self._discover_openrouter, "routerai": self._discover_routerai}
        for provider in PROVIDERS:
            if not self._has_key(provider):
                result[provider] = []
                continue
            if not force and now - self._model_cache_ts.get(provider, 0) < 300 and provider in self._model_cache:
                result[provider] = list(self._model_cache[provider])
                continue
            try:
                models = funcs[provider]()
                if models:
                    self._model_cache[provider] = list(dict.fromkeys(models))
                    self._model_cache_ts[provider] = now
                result[provider] = list(models)
            except Exception as exc:
                self._set_provider_error(provider, f"model discovery: {type(exc).__name__}: {exc}")
                result[provider] = list(self._model_cache.get(provider, []))
        self.gemini_model = self.gemini_model if self.gemini_model in result.get("gemini", []) else (result.get("gemini") or [""])[0]
        self.groq_model = self.groq_model if self.groq_model in result.get("groq", []) else (result.get("groq") or [""])[0]
        self.openrouter_models = [m for m in self.openrouter_models if m in result.get("openrouter", [])] or result.get("openrouter", [])[:10]
        self.openrouter_model = self.openrouter_model if self.openrouter_model in result.get("openrouter", []) else (self.openrouter_models or result.get("openrouter") or [OPENROUTER_FREE_FALLBACK])[0]
        self.routerai_models = [m for m in self.routerai_models if m in result.get("routerai", [])] or result.get("routerai", [])[:10]
        self.routerai_model = self.routerai_model if self.routerai_model in result.get("routerai", []) else (self.routerai_models or result.get("routerai") or [""])[0]
        if self.gemini_model:
            self.gemini.model = self.gemini_model
        return result

    def _models_for(self, provider):
        discovered = self.discover_models(force=False).get(provider, [])
        if provider == "gemini":
            return list(dict.fromkeys([self.gemini_model, *discovered]))[:5]
        if provider == "groq":
            return list(dict.fromkeys([self.groq_model, *discovered]))[:5]
        if provider == "openrouter":
            return list(dict.fromkeys([self.openrouter_model, *self.openrouter_models, *discovered, OPENROUTER_FREE_FALLBACK]))[:8]
        return list(dict.fromkeys([self.routerai_model, *self.routerai_models, *discovered]))[:5]

    def _parse_verdict(self, text):
        if not text:
            return None
        text = str(text).strip()
        candidates = [text]
        match = re.search(r"\{.*\}", text, re.S)
        if match:
            candidates.append(match.group(0))
        for candidate in candidates:
            candidate = candidate.replace("```json", "").replace("```", "").strip()
            try:
                raw = json.loads(candidate)
            except Exception:
                continue
            if not isinstance(raw, dict):
                continue
            risk = str(raw.get("risk", "unknown")).lower().strip()
            if risk not in RISK_SCORE:
                continue
            try:
                confidence = float(raw.get("confidence", 0.75))
            except (TypeError, ValueError):
                confidence = 0.75
            return {"risk": risk, "confidence": max(0.0, min(1.0, confidence)), "reason": str(raw.get("reason", ""))[:1000]}
        return None

    def _prompt(self, event):
        return "Проанализируй событие безопасности VPS. Не выполняй команды. Определи риск.\n" + json.dumps(event, ensure_ascii=False, default=str)

    def _call(self, provider, model, prompt):
        if provider == "gemini":
            key = f"gemini:{model}"
            if not self._healthy(key):
                return None
            try:
                self.gemini.model = model
                result = self.gemini.analyze({"event_type": "security_analysis", "message": prompt})
                if not result:
                    raise RuntimeError(self.gemini.last_error or "empty response")
                self._success(key)
                self.last_provider, self.last_model = provider, model
                return result
            except Exception as exc:
                self._failure(key, 300)
                self._set_provider_error("gemini", f"{model}: {type(exc).__name__}: {exc}")
                return None
        if provider == "routerai":
            key = f"routerai:{model}"
            if not self._healthy(key):
                return None
            result = self.routerai.analyze(model, prompt, allow_paid=self.routerai_allow_paid)
            if result:
                self._success(key)
                self.last_provider, self.last_model = provider, model
                return result
            self._failure(key, 300)
            self._set_provider_error("routerai", self.routerai.last_error or f"{model}: empty response")
            return None
        key = self.groq_key if provider == "groq" else self.openrouter_key
        endpoint = "https://api.groq.com/openai/v1/chat/completions" if provider == "groq" else "https://openrouter.ai/api/v1/chat/completions"
        if not key:
            return None
        for candidate in [model, *self._models_for(provider)]:
            if not candidate or not self._healthy(f"{provider}:{candidate}"):
                continue
            headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json", "Accept": "application/json", "User-Agent": "XFI-Guard/1.6"}
            if provider == "openrouter":
                headers.update({"HTTP-Referer": "https://github.com/deilja/XFI_Guard", "X-Title": "XFI Guard"})
            body = {"model": candidate, "messages": [{"role": "system", "content": "Ты аналитик безопасности VPS. Отвечай по-русски. Верни только JSON: risk=low|medium|high|critical, confidence=0..1, reason=краткое объяснение."}, {"role": "user", "content": prompt}], "temperature": 0, "max_tokens": 500}
            try:
                req = request.Request(endpoint, data=json.dumps(body, ensure_ascii=False).encode(), headers=headers, method="POST")
                with request.urlopen(req, timeout=self.request_timeout) as response:
                    data = json.loads(response.read().decode())
                result = ((data.get("choices") or [{}])[0].get("message") or {}).get("content")
                if result:
                    self._success(f"{provider}:{candidate}")
                    self.last_provider, self.last_model = provider, candidate
                    return result
                raise RuntimeError("empty response")
            except error.HTTPError as exc:
                self._failure(f"{provider}:{candidate}", 300 if exc.code in {401, 403, 404} else 60)
                try:
                    detail = exc.read().decode("utf-8", errors="replace")[:800]
                except Exception:
                    detail = ""
                self._set_provider_error(provider, f"{candidate}: HTTP {exc.code} {detail}")
            except Exception as exc:
                self._failure(f"{provider}:{candidate}")
                self._set_provider_error(provider, f"{candidate}: {type(exc).__name__}: {exc}")
        return None

    def analyze(self, event):
        """Compatibility/public single-analysis API backed by consensus engine."""
        result = self.analyze_consensus(event)
        return result.get("winner", "unknown") if isinstance(result, dict) else None

    def _jobs(self):
        jobs = []
        models = self.discover_models(force=False)
        for provider in self.available_providers():
            candidates = models.get(provider, [])
            if provider == "gemini" and self.gemini_model:
                candidates = [self.gemini_model, *candidates]
            elif provider == "groq" and self.groq_model:
                candidates = [self.groq_model, *candidates]
            elif provider == "openrouter":
                candidates = [self.openrouter_model, *self.openrouter_models, *candidates]
            elif provider == "routerai" and self.routerai_model:
                candidates = [self.routerai_model, *self.routerai_models, *candidates]
            for model in list(dict.fromkeys(candidates)):
                if model and self._healthy(f"{provider}:{model}"):
                    jobs.append((provider, model))
                    break
        return jobs

    def analyze_consensus(self, event):
        self._sync_config()
        self.last_provider_errors = {}
        jobs = self._jobs()
        verdicts = []
        if jobs:
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(self.max_workers, len(jobs))) as pool:
                futures = {pool.submit(self._call, p, m, self._prompt(event)): (p, m) for p, m in jobs}
                for future in concurrent.futures.as_completed(futures):
                    provider, model = futures[future]
                    try:
                        text = future.result()
                        verdict = self._parse_verdict(text)
                        if verdict:
                            verdict.update({"provider": provider, "model": model})
                            verdicts.append(verdict)
                    except Exception as exc:
                        self._set_provider_error(provider, f"{model}: {type(exc).__name__}: {exc}")
        if not verdicts:
            return {"verdicts": [], "providers_used": 0, "models_used": 0, "providers": [], "models": [], "winner": "unknown", "weighted_score": 0.0, "agreement": 0.0, "conflict": 1.0, "confidence": 0.0, "min_consensus": self.min_consensus, "consensus": False, "degraded": True, "mode": "unavailable", "error": "; ".join(f"{p}: {e}" for p, e in self.last_provider_errors.items()), "provider_errors": dict(self.last_provider_errors), "configured_providers": self.configured_providers(), "jobs_attempted": len(jobs)}
        weights = {p: self.weights.get(p, 1.0) for p in PROVIDERS}
        totals = {risk: 0.0 for risk in RISK_SCORE}
        total_weight = 0.0
        for v in verdicts:
            w = weights.get(v["provider"], 1.0) * max(0.01, v["confidence"])
            totals[v["risk"]] += w
            total_weight += w
        winner = max(totals, key=totals.get)
        weighted_score = sum(RISK_SCORE[r] * totals[r] for r in totals) / total_weight if total_weight else 0.0
        agreement = totals[winner] / total_weight if total_weight else 0.0
        confidence = max(v["confidence"] for v in verdicts) if verdicts else 0.0
        consensus = len(verdicts) >= 2 and agreement >= self.min_consensus
        if len(verdicts) == 1:
            consensus = True
        providers = list(dict.fromkeys(v["provider"] for v in verdicts))
        models = list(dict.fromkeys(v["model"] for v in verdicts))
        degraded = len(verdicts) < len(jobs) or len(providers) < len([p for p in self.available_providers() if self._models_for(p)])
        return {"verdicts": verdicts, "providers_used": len(providers), "models_used": len(models), "providers": providers, "models": models, "winner": winner, "weighted_score": round(weighted_score, 4), "agreement": round(agreement, 4), "conflict": round(1 - agreement, 4), "confidence": round(confidence, 4), "min_consensus": self.min_consensus, "consensus": consensus, "degraded": degraded, "mode": "consensus" if len(verdicts) >= 2 else "fallback", "error": "; ".join(f"{p}: {e}" for p, e in self.last_provider_errors.items()), "provider_errors": dict(self.last_provider_errors), "configured_providers": self.configured_providers(), "jobs_attempted": len(jobs)}

    def check_all_providers(self):
        self._sync_config()
        models = self.discover_models(force=True)
        result = []
        for provider in PROVIDERS:
            candidates = models.get(provider, [])
            if provider == "gemini": model = self.gemini_model or (candidates[0] if candidates else "")
            elif provider == "groq": model = self.groq_model or (candidates[0] if candidates else "")
            elif provider == "openrouter": model = self.openrouter_model or (candidates[0] if candidates else "")
            else: model = self.routerai_model or (candidates[0] if candidates else "")
            if not self._has_key(provider) or not model:
                result.append({"provider": provider, "model": model, "ok": False, "error": "not configured"})
                continue
            text = self._call(provider, model, "Ответь только JSON: {\"risk\":\"low\",\"confidence\":1,\"reason\":\"health check\"}")
            result.append({"provider": provider, "model": model, "ok": bool(text), "error": self.last_provider_errors.get(provider, "")})
        return result

    def health(self):
        now = time.monotonic()
        result = {}
        for provider in PROVIDERS:
            entries = {k: v for k, v in self._failures.items() if k.startswith(provider + ":")}
            if not entries:
                result[provider] = {"configured": self._has_key(provider), "healthy": True, "failures": 0, "cooldown_remaining": 0}
            else:
                count, deadline = max(entries.values(), key=lambda x: x[1])
                result[provider] = {"configured": self._has_key(provider), "healthy": deadline <= now, "failures": count, "cooldown_remaining": round(max(0, deadline - now), 1)}
        return result

    def status(self):
        self._sync_config()
        models = self.discover_models(force=False)
        return {"selected_provider": self.provider, "configured_providers": self.configured_providers(), "available_providers": self.available_providers(), "gemini_model": self.gemini_model, "groq_model": self.groq_model, "openrouter_model": self.openrouter_model, "openrouter_models": models.get("openrouter", []), "routerai_enabled": self.routerai_enabled, "routerai_allow_paid": self.routerai_allow_paid, "routerai_model": self.routerai_model, "routerai_models": models.get("routerai", []), "ai_weights": self.weights, "min_consensus": self.min_consensus, "request_timeout": self.request_timeout, "max_workers": self.max_workers, "cooldown": self.cooldown, "health": self.health(), "provider_errors": dict(self.last_provider_errors), "last_error": self.last_error, "last_provider": self.last_provider, "last_model": self.last_model, "ready": self.enabled()}
