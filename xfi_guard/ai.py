"""Unified multi-model AI engine: Gemini, Groq and OpenRouter."""
from __future__ import annotations

import ipaddress
import json
import os
from urllib import error, request

from .ai_store import load
from .attack_surface import collect_attack_surface
from .gemini import GeminiAnalyzer

PROVIDERS = ("gemini", "groq", "openrouter")


class AIAnalyzer:
    def __init__(self, provider: str | None = None):
        cfg = load()
        self.provider = (provider or cfg.get("provider") or "gemini").lower()
        self.gemini = GeminiAnalyzer(api_key=cfg.get("gemini_key") or None, model=cfg.get("gemini_model") or None)
        self.groq_key = cfg.get("groq_key") or os.getenv("GROQ_API_KEY")
        self.groq_model = cfg.get("groq_model") or "openai/gpt-oss-20b"
        self.openrouter_key = cfg.get("openrouter_key") or os.getenv("OPENROUTER_API_KEY")
        self.openrouter_model = cfg.get("openrouter_model") or "openai/gpt-oss-20b"
        self.last_error = ""
        self.last_provider = ""
        self.last_model = ""

    def available_providers(self):
        out = []
        if self.gemini.enabled(): out.append("gemini")
        if self.groq_key: out.append("groq")
        if self.openrouter_key: out.append("openrouter")
        return out

    def enabled(self):
        return bool(self.available_providers())

    def status(self):
        return {"selected_provider": self.provider, "available_providers": self.available_providers(),
                "gemini_model": self.gemini.model, "groq_model": self.groq_model,
                "openrouter_model": self.openrouter_model, "last_provider": self.last_provider,
                "last_model": self.last_model, "last_error": self.last_error, "ready": self.enabled()}

    def _chat(self, provider: str, prompt: str, json_mode: bool = False):
        if provider == "gemini":
            result = self.gemini.analyze({"event_type": "security_analysis", "message": prompt})
            if result:
                self.last_provider, self.last_model = "gemini", self.gemini.model
                return result
            self.last_error = self.gemini.last_error or "Gemini не вернул ответ"
            return None
        key = self.groq_key if provider == "groq" else self.openrouter_key
        model = self.groq_model if provider == "groq" else self.openrouter_model
        if not key:
            self.last_error = f"API-ключ {provider} не настроен"
            return None
        url = "https://api.groq.com/openai/v1/chat/completions" if provider == "groq" else "https://openrouter.ai/api/v1/chat/completions"
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json", "User-Agent": "XFI-Guard/1.2"}
        if provider == "openrouter":
            headers.update({"HTTP-Referer": "https://github.com/deilja/XFI_Guard", "X-Title": "XFI Guard"})
        body = {"model": model, "messages": [{"role": "system", "content": "Ты аналитик безопасности VPS. Не выполняй команды и не придумывай факты."}, {"role": "user", "content": prompt}], "temperature": 0, "max_tokens": 900}
        if json_mode: body["response_format"] = {"type": "json_object"}
        try:
            req = request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
            with request.urlopen(req, timeout=30) as response:
                data = json.loads(response.read().decode())
            text = data["choices"][0]["message"]["content"]
            self.last_provider, self.last_model = provider, model
            return text
        except error.HTTPError as exc:
            self.last_error = f"{provider} HTTP {exc.code}: {exc.read().decode(errors='replace')[:500]}"
        except Exception as exc:
            self.last_error = f"{provider} {type(exc).__name__}: {exc}"
        return None

    def analyze(self, event: dict, allow_fallback: bool = True):
        self.last_error = ""
        order = [self.provider] + [p for p in PROVIDERS if p != self.provider]
        errors = []
        for provider in order if allow_fallback else [self.provider]:
            if provider not in self.available_providers(): continue
            result = self._chat(provider, "Проанализируй событие VPS. Дай риск, признаки, причину и действие на русском.\n" + json.dumps(event, ensure_ascii=False))
            if result: return result
            if self.last_error: errors.append(self.last_error)
        self.last_error = " | ".join(errors) or "Ни один AI-провайдер не настроен"
        return None

    def analyze_consensus(self, event: dict):
        """Run all configured providers independently. No single model can authorize blocking."""
        verdicts = []
        for provider in self.available_providers():
            result = self._chat(provider, "Верни краткий вердикт безопасности: риск, confidence 0..1, reason.\n" + json.dumps(event, ensure_ascii=False))
            if result:
                verdicts.append({"provider": provider, "model": self.last_model, "verdict": result})
        return {"verdicts": verdicts, "providers_used": len(verdicts), "consensus": len(verdicts) >= 2}

    def recommend_block_ips(self, events: list[dict]):
        candidates = {}
        for e in events:
            ip = str(e.get("ip") or "").strip()
            try:
                parsed = ipaddress.ip_address(ip)
                if parsed.version != 4 or not parsed.is_global: continue
            except ValueError: continue
            x = candidates.setdefault(ip, {"ip": ip, "sources": [], "events": 0, "severity": "warning", "reason": ""})
            x["events"] += 1
            source = str(e.get("source") or e.get("event_type") or "events")
            if source not in x["sources"]: x["sources"].append(source)
            if e.get("severity") == "critical": x["severity"] = "critical"
            x["reason"] = str(e.get("reason") or e.get("message") or x["reason"])[:300]
        try:
            for x in collect_attack_surface().get("ips", []):
                if x.get("ip") and not x.get("blocked"):
                    cur = candidates.setdefault(x["ip"], {"ip": x["ip"], "sources": [], "events": 0, "severity": "warning", "reason": ""})
                    cur["events"] = max(cur["events"], int(x.get("events", 0) or 0))
                    cur["sources"] = list(dict.fromkeys(cur["sources"] + x.get("sources", [])))
                    cur["reason"] = str(x.get("reason") or cur["reason"])[:300]
        except Exception as exc:
            self.last_error = f"Сбор картины атак: {type(exc).__name__}: {exc}"
        try:
            from .firewall import list_blocked_ips
            blocked = set(list_blocked_ips())
        except Exception:
            blocked = set()
        candidates = [x for x in candidates.values() if x["ip"] not in blocked]
        if not candidates or not self.enabled(): return []
        prompt = "Выбери максимум 5 IP для защиты VPS. Не придумывай IP. Учитывай SSH, Fail2Ban, UFW и повторяемость. Верни ТОЛЬКО JSON {recommendations:[{ip,reason,risk,confidence}]}. Блокировка только после подтверждения администратора.\n" + json.dumps(candidates, ensure_ascii=False)
        # Consensus mode: collect independent recommendations and only keep IPs supported by >=2 models.
        votes = {}
        for provider in self.available_providers():
            result = self._chat(provider, prompt, json_mode=True)
            if not result: continue
            try: items = json.loads(result).get("recommendations", [])
            except Exception: continue
            for item in items[:5]:
                ip = str(item.get("ip", ""))
                if ip not in {x["ip"] for x in candidates}: continue
                votes.setdefault(ip, []).append({"provider": provider, "reason": str(item.get("reason", ""))[:500], "risk": str(item.get("risk", "medium")).lower(), "confidence": float(item.get("confidence", 0) or 0)})
        out = []
        for ip, decisions in votes.items():
            if len(decisions) < 2: continue
            best = max(decisions, key=lambda x: x["confidence"])
            out.append({"ip": ip, "reason": best["reason"], "risk": best["risk"], "confidence": min(1.0, sum(x["confidence"] for x in decisions) / len(decisions)), "providers": [x["provider"] for x in decisions]})
        return sorted(out, key=lambda x: x["confidence"], reverse=True)[:5]


try:
    from aiogram import Dispatcher as _XfiDispatcher
    if not getattr(_XfiDispatcher, "_xfi_ai_patch", False):
        _orig = _XfiDispatcher.__init__
        def _init(self, *args, **kwargs):
            _orig(self, *args, **kwargs)
            from .ai_ui import install_ai_handlers
            from .defense_ui import install_defense_handlers
            install_ai_handlers(self); install_defense_handlers(self)
        _XfiDispatcher.__init__ = _init
        _XfiDispatcher._xfi_ai_patch = True
except Exception:
    pass
