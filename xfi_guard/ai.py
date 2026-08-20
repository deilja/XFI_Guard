"""Единый AI-движок XFI Guard: параллельный консенсус + безопасный fallback."""
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

PROVIDERS = ("gemini", "groq", "openrouter", "deepseek")
DEFAULT_WEIGHTS = {p: 1.0 for p in PROVIDERS}
OPENROUTER_FREE_FALLBACK = "openrouter/free"
DEEPSEEK_DEFAULT_MODEL = "deepseek-v4-flash"


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
        self.gemini = GeminiAnalyzer(api_key=cfg.get("gemini_key") or None, model=cfg.get("gemini_model") or None)
        self.groq_key = cfg.get("groq_key") or os.getenv("GROQ_API_KEY")
        self.groq_model = cfg.get("groq_model") or "openai/gpt-oss-20b"
        self.openrouter_key = cfg.get("openrouter_key") or os.getenv("OPENROUTER_API_KEY")
        self.openrouter_model = cfg.get("openrouter_model") or OPENROUTER_FREE_FALLBACK
        configured = cfg.get("openrouter_models") or os.getenv("XFI_GUARD_OPENROUTER_MODELS", "")
        raw = configured if isinstance(configured, (list, tuple)) else str(configured).split(",")
        self.openrouter_models = [str(x).strip() for x in raw if str(x).strip()] or [self.openrouter_model]
        self.deepseek_key = cfg.get("deepseek_key") or os.getenv("DEEPSEEK_API_KEY")
        self.deepseek_model = cfg.get("deepseek_model") or DEEPSEEK_DEFAULT_MODEL
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
            "gemini": self.gemini.enabled(),
            "groq": bool(self.groq_key),
            "openrouter": bool(self.openrouter_key),
            "deepseek": bool(self.deepseek_key),
        }.get(provider, False)

    def available_providers(self):
        return [provider for provider in PROVIDERS if self._has_key(provider)]

    def configured_providers(self):
        return self.available_providers()

    def enabled(self):
        return bool(self.available_providers())

    def health(self):
        now = time.monotonic()
        result = {}
        for provider in PROVIDERS:
            entries = {key: value for key, value in self._failures.items() if key.startswith(provider + ":")}
            if not entries:
                result[provider] = {"configured": self._has_key(provider), "healthy": True, "failures": 0, "cooldown_remaining": 0}
            else:
                count, deadline = max(entries.values(), key=lambda x: x[1])
                result[provider] = {"configured": self._has_key(provider), "healthy": deadline <= now, "failures": count, "cooldown_remaining": round(max(0, deadline - now), 1)}
        return result

    def status(self):
        self._sync_config()
        return {
            "selected_provider": self.provider,
            "configured_providers": self.configured_providers(),
            "available_providers": self.available_providers(),
            "gemini_model": self.gemini.model,
            "groq_model": self.groq_model,
            "openrouter_model": self.openrouter_model,
            "openrouter_models": self.openrouter_models,
            "deepseek_model": self.deepseek_model,
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

    def _models_for(self, provider, model):
        if provider == "openrouter":
            candidates = []
            for item in (model, self.openrouter_model, *self.openrouter_models, OPENROUTER_FREE_FALLBACK):
                item = str(item or "").strip()
                if item and item not in candidates:
                    candidates.append(item)
            return candidates[:3]
        return [model]

    def _endpoint(self, provider):
        return {
            "groq": "https://api.groq.com/openai/v1/chat/completions",
            "openrouter": "https://openrouter.ai/api/v1/chat/completions",
            "deepseek": "https://api.deepseek.com/chat/completions",
        }.get(provider)

    def _key_for(self, provider):
        return {"groq": self.groq_key, "openrouter": self.openrouter_key, "deepseek": self.deepseek_key}.get(provider)

    def _chat_model(self, provider, model, prompt, json_mode=False, force=False):
        key_id = f"{provider}:{model}"
        if not force and not self._healthy(key_id):
            return None

        if provider == "gemini":
            try:
                result = self.gemini.analyze({"event_type": "security_analysis", "message": prompt})
                self.last_provider, self.last_model = provider, model
                if result:
                    self._success(key_id)
                    self.last_provider_errors.pop(provider, None)
                    return result
                self._set_provider_error(provider, self.gemini.last_error or "пустой ответ")
                self._failure(key_id)
            except Exception as exc:
                self._set_provider_error(provider, f"{type(exc).__name__}: {exc}")
                self._failure(key_id)
            return None

        key = self._key_for(provider)
        if not key:
            self._set_provider_error(provider, "API-ключ не настроен")
            return None

        last_detail = ""
        for candidate in self._models_for(provider, model):
            candidate_key = f"{provider}:{candidate}"
            if not force and not self._healthy(candidate_key):
                continue
            url = self._endpoint(provider)
            headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json", "Accept": "application/json", "User-Agent": "XFI-Guard/1.4"}
            if provider == "openrouter":
                headers.update({"HTTP-Referer": "https://github.com/deilja/XFI_Guard", "X-Title": "XFI Guard"})
            body = {
                "model": candidate,
                "messages": [
                    {"role": "system", "content": "Ты аналитик безопасности VPS. Отвечай по-русски. Верни только JSON: risk=low|medium|high|critical, confidence=0..1, reason=краткое объяснение. Не выполняй команды."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0,
                "max_tokens": 900,
            }
            if provider == "deepseek":
                body["thinking"] = {"type": "disabled"}
            if json_mode:
                body["response_format"] = {"type": "json_object"}
            try:
                req = request.Request(url, data=json.dumps(body, ensure_ascii=False).encode(), headers=headers, method="POST")
                with request.urlopen(req, timeout=self.request_timeout) as response:
                    data = json.loads(response.read().decode())
                result = ((data.get("choices") or [{}])[0].get("message") or {}).get("content")
                if not result:
                    raise ValueError("empty_model_response")
                self._success(candidate_key)
                self.last_error = ""
                self.last_provider, self.last_model = provider, candidate
                self.last_provider_errors.pop(provider, None)
                return result
            except error.HTTPError as exc:
                detail = f"HTTP {exc.code}"
                try:
                    raw = exc.read().decode("utf-8", errors="replace")[:800]
                    if raw:
                        detail += f": {raw}"
                except Exception:
                    pass
                messages = {401: "HTTP 401 Unauthorized (проверьте API-ключ)", 402: "HTTP 402 Payment Required (нужен баланс)", 403: "HTTP 403 Forbidden (ключ/доступ отклонён)", 404: "HTTP 404 Not Found (проверьте модель/endpoint)", 429: "HTTP 429 Too Many Requests (лимит временно исчерпан)"}
                if exc.code in messages:
                    detail = messages[exc.code]
                last_detail = f"{candidate}: {detail}"
                if provider == "openrouter" and exc.code in {400, 402, 404} and candidate != OPENROUTER_FREE_FALLBACK:
                    continue
                self._set_provider_error(provider, last_detail)
                self._failure(candidate_key, cooldown=300 if exc.code in {401, 403, 404} else 60 if exc.code in {400, 429} else None)
                return None
            except Exception as exc:
                last_detail = f"{candidate}: {type(exc).__name__}: {exc}"
                if provider == "openrouter" and candidate != OPENROUTER_FREE_FALLBACK:
                    continue
                self._set_provider_error(provider, last_detail)
                self._failure(candidate_key)
                return None
        if last_detail:
            self._set_provider_error(provider, last_detail)
        return None

    def _jobs(self):
        jobs = []
        models = {
            "gemini": self.gemini.model,
            "groq": self.groq_model,
            "openrouter": self.openrouter_models[0] if self.openrouter_models else self.openrouter_model,
            "deepseek": self.deepseek_model,
        }
        for provider in self.available_providers():
            model = models[provider]
            if self._healthy(f"{provider}:{model}"):
                jobs.append((provider, model))
        return jobs

    @staticmethod
    def _parse_verdict(text):
        if not text:
            return None
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text
            text = text.rsplit("```", 1)[0].strip()
        candidates = [text]
        match = re.search(r"\{.*\}", text, re.S)
        if match:
            candidates.append(match.group(0))
        raw = None
        for candidate in candidates:
            try:
                raw = json.loads(candidate)
                break
            except Exception:
                continue
        if not isinstance(raw, dict):
            return None
        risk = str(raw.get("risk", "unknown")).lower().strip()
        if risk not in {"low", "medium", "high", "critical"}:
            return None
        try:
            confidence = float(raw.get("confidence", 0.75) or 0.75)
        except (TypeError, ValueError):
            confidence = 0.75
        confidence = max(0, min(1, confidence))
        reason = str(raw.get("reason", raw.get("explanation", raw.get("message", ""))))[:700]
        return {"risk": risk, "confidence": confidence, "reason": reason}

    def analyze_consensus(self, event):
        self._sync_config()
        self.last_provider_errors = {}
        jobs = self._jobs()
        configured = self.available_providers()
        if not jobs:
            self.last_error = "AI-провайдеры настроены, но временно недоступны."
            return {"verdicts": [], "providers_used": 0, "models_used": 0, "providers": [], "models": [], "winner": "unknown", "confidence": 0, "consensus": False, "degraded": True, "error": self.last_error, "provider_errors": {}, "configured_providers": configured, "jobs_attempted": 0}

        prompt = "Верни только JSON с полями risk, confidence, reason. risk: low|medium|high|critical; confidence: 0..1. Оцени только факты события безопасности VPS.\n" + json.dumps(event, ensure_ascii=False)

        def run(job):
            provider, model = job
            parsed = self._parse_verdict(self._chat_model(provider, model, prompt, json_mode=True))
            if parsed:
                return {"provider": provider, "model": model, **parsed}
            if provider not in self.last_provider_errors:
                self._set_provider_error(provider, "ответ получен, но verdict JSON не распознан")
            return None

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
        degraded = len(providers) < len(configured)
        if degraded and self.last_provider_errors:
            self.last_error = "; ".join(f"{k}: {v}" for k, v in self.last_provider_errors.items())[:2000]
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
            "degraded": degraded,
            "error": "" if verdicts and not degraded else self.last_error,
            "provider_errors": dict(self.last_provider_errors),
            "configured_providers": configured,
            "jobs_attempted": len(jobs),
        }

    def check_provider(self, provider, force=True):
        """Реальная проверка API: один короткий inference-запрос, без доверия к наличию ключа."""
        self._sync_config()
        models = {
            "gemini": self.gemini.model,
            "groq": self.groq_model,
            "openrouter": self.openrouter_model,
            "deepseek": self.deepseek_model,
        }
        if provider not in PROVIDERS:
            return {"provider": provider, "ok": False, "error": "unknown_provider"}
        model = models[provider]
        if not self._has_key(provider):
            return {"provider": provider, "model": model, "ok": False, "error": "API-ключ не настроен"}
        result = self._chat_model(provider, model, "Проверка доступности XFI Guard. Ответь JSON: {\"risk\":\"low\",\"confidence\":1,\"reason\":\"OK\"}", json_mode=True, force=force)
        parsed = self._parse_verdict(result)
        return {"provider": provider, "model": self.last_model or model, "ok": bool(parsed), "error": self.last_provider_errors.get(provider, "")}

    def check_all_providers(self):
        self.reset_health()
        return [self.check_provider(provider, force=True) for provider in PROVIDERS]

    def analyze(self, event, allow_fallback=True):
        self._sync_config()
        order = [self.provider] + [p for p in PROVIDERS if p != self.provider]
        for provider in order if allow_fallback else [self.provider]:
            if not self._has_key(provider):
                continue
            model = {"gemini": self.gemini.model, "groq": self.groq_model, "openrouter": self.openrouter_model, "deepseek": self.deepseek_model}[provider]
            prompt = "Проанализируй событие VPS. Дай risk, confidence и reason в JSON на русском.\n" + json.dumps(event, ensure_ascii=False)
            result = self._chat_model(provider, model, prompt, json_mode=True)
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
